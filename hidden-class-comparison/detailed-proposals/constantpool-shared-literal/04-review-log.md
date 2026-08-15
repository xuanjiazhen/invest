# 审视日志（ConstantPool 跨 VM 共享与字面量优化）

本文档独立保存 5 轮不同角色审视记录与闭环意见，不混入正式方案文档。审视对象：01-背景 / 02-需求 / 03-方案设计。

## 第 1 轮：项目管理者（PM）

**审视意见**
1. 两个子方向收益都未量化（置信度 55–60%），立项依据是否充分？
2. 多 VM（worker）场景在 Top13 应用中是否真实存在、占比如何？

**闭环结论**
- 采纳：前置插桩统计设为立项门槛（多 VM 字符串重复量、字面量对象规模），收益明确前不进入开发排期（需求 §3 已标注）；
- 采纳：补做「多 VM/worker 场景规模调研」（应用 worker 使用率、每 worker 加载 abc 数），作为立项数据。

## 第 2 轮：SE / 架构师

**审视意见**
1. 字符串表跨 VM 共享与 VM 私有生命周期（GC、teardown）如何协调？
2. 对象字面量 HClass 跨 VM 共享是否违反「HClass 堆归属」约束？

**闭环结论**
- 澄清：共享字符串归 shared heap（Runtime 级），worker teardown 不清共享字符串，由 shared GC 管理；非 sendable 只读字符串走共享只读字符串表（方案设计 §4.1）；
- 采纳：HClass 跨 VM 仅限 read-only 空间（方案设计 §4.2 已写明受堆归属约束）。

## 第 3 轮：测试工程师

**审视意见**
1. COW 写时复制的并发写场景（两线程同时写同一 backing）如何验证？
2. 多 VM 共享字符串的悬垂引用场景？

**闭环结论**
- 采纳：DT 用例含「对象字面量 COW 并发写」（一个实例修改不影响其他）+ 写屏障验证；
- 采纳：worker teardown + 主 VM 存活 + shared GC 组合压力测试，验证无悬垂。

## 第 4 轮：VM / 编译器开发者

**审视意见**
1. `EcmaStringTableMutex` 的并发 intern 粒度是否足够？热路径是否受锁影响？
2. 对象字面量 COW 化后，`CloneProperties` 的深克隆路径是否完全替换？

**闭环结论**
- 澄清：并发 intern 只覆盖首次（锁），后续 CAS/只读（方案设计 §4.1）；热路径用 fast path 无锁；
- 采纳：COW 化后 `CloneObjectLiteral` 的深克隆路径按「backing COW 共享 + 写时复制」改造，`CloneProperties` 仅在有写时才复制。

## 第 5 轮：发布 / 兼容性负责人

**审视意见**
1. shared 字符串与 sendable 字符串的语义差异对应用可见行为的影响？
2. 多 VM 场景的镜像/版本管理？

**闭环结论**
- 澄清：共享字符串保持 intern 去重语义（=== 一致），sendable 字符串语义不变；
- 采纳：共享字符串不改变字节码/API/镜像格式，版本管理沿用既有机制。

## 第 6 轮：独立复核（源码重验证 + 快照数据复算）

**核验结果**（基线 `ets_runtime`）：

1. 归属关系核验一致：`unsharedConstpools_` 每 VM 一份且 GC 每 VM 遍历（`ecma_vm.cpp:505-512,1118-1120`）、字符串表每 VM 一份（`ecma_vm.h:1776`）、shared 池在 Runtime 级（`runtime.cpp:83-90,586-598`）、`NewSClassLiteral`（`jspandafile/program_object.cpp:47`）、`GetObjectLiteralRootHClass` 每 VM GlobalEnv 缓存（`object_factory.cpp:4415-4436`）、数组字面量 COW ≤10 元素（`object_factory.cpp:539-560`）。
2. **子方向 A 上界量化完成（原为未量化）**：对 13 份快照复算，ConstantPool 持有的**去重后**字符串对象 685,129 个 / 15.38 MiB（`evidence/top13-layout-dedup-census.json`）。每多一个加载同 abc 的 VM，重复上界即该值按加载子集折减。这既给 A 划定了天花板（约 15 MiB/VM），也提示：**若 Top13 应用实际不使用 worker 或 worker 不加载业务 abc，A 的收益趋近于零**——worker 场景调研从「立项数据」升级为「一票否决项」。
3. **子方向 B 的 HClass 缓存项剔除**：`GetObjectLiteralRootHClass` 缓存容量为 `MAX_LITERAL_HCLASS_CACHE_SIZE+1`（几十个 root HClass），跨 VM 共享的收益上限为每 VM 数 KB，量级可忽略——B 收窄为「backing COW/模板克隆」，收益主体是时间与峰值而非稳态驻留。
4. **设计缺口补齐（hash 并发安全）**：shared 字符串被多 VM 引用后，EcmaString 惰性 hash 回写存在数据竞争窗口，须 CAS/预计算并以 TSAN 验证——已补入 §4.1 第 4 条与 DT「shared hash 并发计算」用例。
5. resolved 条目构成复核：method 54.2% / class_literal 17.4% / string 17.1%（census 证据文件），Method/ClassLiteral 不可共享的边界描述正确。

**闭环结论**：01/02/03 已按本轮更新（A 上界 15.38 MiB 落稿、B 收窄、hash 并发设计点、DT 补用例）。**立项顺序建议：worker 场景调研 → 若乘数为 0 则 A 撤项；B 先做字面量占比归因再排期。**无其他遗留。

## 第 7 轮：人工审视 TODO 闭环（前置插桩 patch）

**人工意见**：针对「立项顺序建议：worker 场景调研 → 若乘数为 0 则 A 撤项；B 先做字面量占比归因再排期」给出插桩 patch，以便人工复核。

**闭环结论**：新增 `05-插桩patch.md`——VM 生命周期 + abc 加载矩阵（`EcmaVM` 构造/析构 + `JSPandaFileManager` 加载路径）得 `k(abc)` 并发重叠数与撤项判据 `Σ(k−1)==0`；`CloneObjectLiteral/CloneArrayLiteral`（`object_factory.cpp:517/539`）计数得创建口径；abc 级 CP 字符串字节（`program_object.cpp` resolve 路径）与 `k(abc)` 相乘得 A 收益；dump 侧字面量驻留归因（`rawheap_dump.cpp:650` 一带）得 B 空间口径。01-背景 §6 已链接。

## 审视结论汇总

前 5 轮 8 项意见全部闭环；第 6 轮独立复核 5 项（归属核验、A 上界量化、B 收窄、hash 并发补齐、构成复核），已同步落稿。遗留：worker 场景调研与字面量占比归因两个前置量化项。
