# 审视日志（Native Interop 闭包惰性原型绑定）

本文档独立保存各轮不同角色审视记录与闭环意见，不混入正式方案文档。审视对象：01-背景 / 02-需求 / 03-方案设计 / 05-插桩patch。历史结论若被后续 7.0 Release 源码核查推翻，以最新更新为准。

## 第 1 轮：项目管理者（PM）

**审视意见**
1. 收益期望值未知（61 MiB 是上界），前置插桩统计的成本与周期如何？是否阻塞排期？
2. A1/A2 选型对排期影响差异大，如何决策？

**闭环结论**
- 采纳：插桩统计（5–8 人日）设为**前置里程碑**，输出「整类未触及占比 vs 单方法未读取占比」两个比例后再冻结 A1/A2 选型与排期；需求 §3 已标注 A1 3–5 人周、A2 6–9 人周为选型后细化值。
- 处理：需求文档 §3 补「需先插桩定收益与选型后细化」。

## 第 2 轮：SE / 架构师

**审视意见**
1. `InternalAccessor::InternalGetFunc` 签名不接收属性键——A2 形态一每方法 24 B 对象 vs 形态二改 property 全路径，架构上哪个更可持续？
2. `ResetLazyInternalAttr` 原地改共享 LayoutInfo，对同 HClass 的其他 prototype 与已建 IC 的影响范围？

**闭环结论**
- 澄清：形态一实现成本低但每方法常驻 24 B（相对 184 B 仍省 87%）；形态二零残留但改 property lookup 全路径——**架构上形态二更优，作为 A2 目标形态**，形态一为过渡。
- 采纳：原地 attr 改写会触发原型链 IC 失效，须在实现中显式核对（方案设计 §4.3 已列为硬性处理项）；materialize 用 per-slot 原子状态机。

## 第 3 轮：测试工程师

**审视意见**
1. 插桩统计的抽样场景（冷启动/主流程/后台驻留）是否覆盖「采样后才实例化」的时序偏差？
2. property semantics 矩阵是否覆盖反射拷贝（`Object.assign`/展开、proxy 不变量）？

**闭环结论**
- 采纳：插桩按三档场景导出首次读取时刻，明确区分「采样后实例化」与「访问而不实例化」两类时序（背景 §4 已分析）；
- 采纳：验证矩阵补反射拷贝与 proxy trap 不变量校验（方案设计附录一）。

## 第 4 轮：VM / NAPI 开发者

**审视意见**
1. descriptor 深拷贝后 `data` 字段的资源所有权仍归模块定义，如何保证 module unload 时不重复释放？
2. materialize 状态机的异常重入（首次访问中抛异常）如何保证不半初始化？

**闭环结论**
- 澄清：深拷贝复制名称与 data 指针，但 data 指向资源的释放所有权仍归模块（方案设计 §6 已写明）；module unload 路径验证未 materialize 的 descriptor 不重复释放（DT 用例）。
- 采纳：per-slot 原子状态机（创建→发布→完成），异常路径回滚为惰性态，二次访问重试。

## 第 5 轮：发布 / 兼容性负责人

**审视意见**
1. 三方模块的 descriptor 静态存储期契约如何文档化与版本化？
2. sendable 类排除后的边界与回归范围？

**闭环结论**
- 澄清：默认走深拷贝（不改接口契约）；零拷贝静态存储期入口需在 NAPI 文档中声明并纳入兼容性测试；
- 采纳：sendable 类保留即时路径，排除逻辑与回归用例在 DT 矩阵单列。

## 第 6 轮：独立复核（源码重验证）

**核验结果**（基线 `ets_runtime` + `foundation/arkui/napi`）：

1. 调用链行号逐点核验一致：`napi_define_class`（`ark_native_engine.cpp:333`）→ `NapiCreateClassFunction`（:288）→ `NapiGetKeysAndAttrsFromProps`（:250）→ `NapiInitAttrValFromProp`（:216）→ `NapiNativeCreateFunction`（:190）→ `FunctionRef::NewConcurrentWithName`（`jsnapi_expo.cpp:3947`）。
2. 惰性机制先例核验一致：`Builtins::SetLazyAccessor`（`builtins.cpp:479`）、`builtins_lazy_callback.cpp`（Date/Set/Map/WeakMap 等逐槽惰性）、`InternalAccessor` 24 B（`Record::SIZE=8` + getter 8 B + setter 8 B）、`InternalGetFunc` 签名确不含属性键——A2 形态一每方法一个 24 B 对象的结论成立。
3. **设计缺口补齐（IC 失效机制未具体化）**：原方案只写「IC 失效正确」，未指定机制。已补 §4.4：materialize 须走 `MarkProtoChanged` + listener 刷新 + MegaIC 清理的既有链路，并给出「热访问建 IC → materialize → 旧 handler 不得命中」的验证方法。
4. **成本缺口补齐（descriptor 深拷贝驻留）**：A2 下 descriptor 数组存活期从「define_class 期间」延长为「至首次访问/卸载」，堆外新增 72–96 B/方法，直接抵扣收益——已补 §4.5 量化要求与 20% 触发的静态存储期备选路径，需求 §4 增列该风险。
5. **插桩点细化**：原插桩只统计「是否被读取」，未区分会强制 materialize 的 descriptor 形态读取（能力探测/序列化）——已补 §4.6「读取形态」单列，避免收益高估。
6. 01-背景 §2 的尺寸事实（JSFunction 112/136/144 B、JSNativePointer 40 B、函数 hclass 每 context 一份 88 B）与快照 self_size 口径一致。

**历史闭环结论（已被第 10 轮修正）**：01/02/03 曾按本轮更新（§4.4 IC 失效机制、§4.5 descriptor 驻留量化、§4.6 插桩形态区分；需求 §4 新增两项风险）落稿。该结论只说明当时文档内部闭环，不代表插桩已通过目标 Release 源码核查。

## 第 7 轮：人工审视项闭环（插桩 patch）

**人工意见**：「给出插桩统计『从未被读取的方法占比』的 patch 改动，以便人工进行插桩统计。」

**历史结论（已被第 10 轮修正）**：曾新增 `05-插桩patch.md`，提出创建侧登记、native 回调 wrapper、`JSObject::GetProperty:1396` 慢路径、`napi_new_instance:1512` 和逐项 TSV 输出。该版本未基于 7.0 Release 逐项核查，不能作为实施依据。

## 审视结论汇总（第 1–7 轮）

前 5 轮 8 项意见全部闭环；第 6 轮独立复核 6 项（链路核验、机制核验、IC 失效具体化、descriptor 成本量化、插桩形态细化、尺寸口径确认），已同步落稿。第 7 轮提出的插桩方案后来经第 10 轮 Release 源码复核修正，历史内容保留用于追溯，不再作为当前实施结论。

## 第 8 轮：Kuaishou 后台 full-GC 快照复核（历史 schema v3，已由第 12 轮废止）

**评估口径**：前台与后台 rawheap 使用同一 API 26 `rawheap_translator` 2.0.0 转换；后台为应用进入后台并执行全量 GC 后的独立存活堆。本轮只构造 A2 **结构候选上界**：HClass 无存活实例、prototype 直接持有非 `constructor` native-stub 方法、且闭包自身持有唯一 `JSNativePointer`。该条件不等价于“从未读取/调用”。冻结数据见 `evidence/kuaishou-background-paired-census.json`。

| 指标 | 前台 Kuaishou | 后台 full-GC Kuaishou | 后台相对前台 |
|---|---:|---:|---:|
| 结构候选 prototype / 方法槽 | 70 / 463 | 75 / 576 | +5 / +113 |
| 闭包 + JSNativePointer 浅层毛收益 | 84,648 B | 104,128 B | +19,480 B |
| `NapiFunctionInfo` 堆外模型 | 14,816–18,520 B | 18,432–23,040 B | +3,616–4,520 B |
| 毛收益合计 | 99,464–103,168 B（0.095–0.098 MiB） | 122,560–127,168 B（0.117–0.121 MiB） | +23,096–24,000 B |
| X1 `NapiLazyAccessor` | 14,816 B | 18,432 B | +3,616 B |
| 历史连续 recipe + 1 B state（已废止） | 7,872 B | 9,792 B | +1,920 B |
| 历史模型 class overhead 前条件净收益（已废止） | 76,776–80,480 B（0.073–0.077 MiB） | 94,336–98,944 B（0.090–0.094 MiB） | +17,560–18,464 B |
| 历史模型未读取率 break-even（已废止） | 8.91%–9.30% | 9.01%–9.40% | — |

**历史结论（已由第 12 轮废止）**：后台结构候选上界比前台高，但这反映两个采样时点的存活结构差异，不能解释为 full-GC 使真实收益增加。full-GC 只确认这些 prototype/闭包在后台采集时仍存活；它不记录属性是否曾读取、方法是否曾调用或反射形态读取。该表使用 schema v3 的连续 recipe + 1 B state 模型，仅保留用于审视追溯，不再作为正式成本或收益结论。

## 第 9 轮：Top13 61.47 MiB 应用归属与口径闭环

使用 `scripts/measure_lazy_binding_targets.py` 1.1.0 对原 Top13 的 13 份 `.heapsnapshot` 重放，并将 Bucket C 拆成「prototype 方法闭包」和「类构造器闭包」。完整冻结结果见 [`top13-native-interop-method-census.json`](../../evidence/top13-native-interop-method-census.json)。

| 排名 | 应用 | 方法闭包数 | 方法闭包本体 | 占 61.47 MiB 比例 |
|---:|---|---:|---:|---:|
| 1 | **kuaishou** | **175,025** | **24.035 MiB** | **39.10%** |
| 2 | weibo | 41,973 | 5.763 MiB | 9.37% |
| 3 | douyin | 40,814 | 5.604 MiB | 9.12% |
| 4 | pinduoduo | 34,078 | 4.678 MiB | 7.61% |
| 5 | jingdong | 31,827 | 4.369 MiB | 7.11% |
| — | Top13 合计 | 447,707 | 61.474 MiB | 100.00% |

**口径闭合**：方案中的 `447,707 / 61.47 MiB` 只统计零实例类 prototype 上的**方法闭包**。同批快照另有 57,737 个与类同名的构造器闭包（7.062 MiB）；加入构造器后是 505,444 个、68.536 MiB。因此历史文档中的 `61.47 MiB` 与应用侧分析中的 `68.54 MiB` 不是互相矛盾的两个测量值，而是前者排除、后者包含构造器。

**对人工问题的回答**：原 Top13 的 61.47 MiB 中，贡献最多的仍是 **kuaishou**，为 24.035 MiB、占 39.10%，明显高于第二名 weibo 的 5.763 MiB。

### Kuaishou 前后台方法闭包空间刷新

按 `24.035 MiB` 的方法闭包语义口径刷新：共享 native stub、零存活实例类的 prototype 直接持有、排除 `constructor`，只累计唯一方法闭包的实际 `self_size`；不要求闭包具有可见且唯一的 `JSNativePointer`。前台使用 Top13 Kuaishou 同一份原 rawheap，前后台均由 API 26 `rawheap_translator` 2.0.0 转换。冻结数据见 [`kuaishou-background-paired-census.json`](../../evidence/kuaishou-background-paired-census.json) 的 `method_only_structural_upper_bound`。

| 指标 | 前台 Kuaishou | 后台 full-GC Kuaishou | 后台相对前台 |
|---|---:|---:|---:|
| 候选 prototype | 336 | 172 | -164 |
| 方法属性槽 | 1,389 | 1,038 | -351 |
| **唯一方法闭包** | **1,378** | **1,034** | **-344** |
| **方法闭包浅层大小** | **197,096 B（0.188 MiB）** | **146,696 B（0.140 MiB）** | **-50,400 B（-0.048 MiB）** |
| 排除的构造器闭包 | 116 / 14,480 B | 116 / 14,144 B | 0 / -336 B |

因此，在 API26 translator 的同口径前后台快照中，可观察到的方法闭包结构上界是：前台 **1,378 个、0.188 MiB**，后台 **1,034 个、0.140 MiB**。方法属性槽多于唯一闭包，是因为少量闭包由多个属性槽引用。

该数值仍是**结构上界**：零存活实例不证明类名或方法从未被读取，也不证明闭包可全部消除；真实可优化量仍需读取/调用插桩和 clean A/B。历史 `24.035 MiB` 来自同一前台 rawheap 的旧 translator 输出；旧、新 translator 的 prototype/HClass 和属性边表达不同，不能将 `24.035 MiB` 与新前台 `0.188 MiB` 相减并解释为版本收益。

第 8 轮 strict A2 模型是上述方法闭包结构上界进一步限制为“闭包具有唯一可见 `JSNativePointer`”后，按 463/576 个 property slots 扣除 X1 accessor、最小 method/data recipe 与 state 得到的 `before class overhead` 条件净收益，不是方法闭包本体大小；两套数字不混用。

## 第 10 轮：7.0 Release 插桩可行性复核

**核验基线**：manifest `OpenHarmony-7.0-Release@4ad97323baf64f52922c5dadcbbd11754732a057`；`arkcompiler_ets_runtime@f04900cf951c66c2ea18b2bab5b591d5336c34b9`；`foundation/arkui/napi@464170c9c1faba39f56549a13d232d51740a49d3`。

**结论**：第 7 轮的 wrapper、`callbackPtr`、`JSObject::GetProperty` 单点读取、`napi_new_instance` 实例化标记和自定义 TSV 均不可作为 7.0 Release 实施 patch。`ArkNativeFunctionCallBack` 已通过 `runtimeInfo->GetData()` 获取真实 `NapiFunctionInfo`，应以 `NapiFunctionInfo *` 作为外置 registry entry 的活跃键，不修改其布局、不包装原 callback；属性读取必须覆盖解释器快路径、IC、compiler/AOT 和 descriptor/反射路径，未闭合前只能报告 Phase 1 callback 调用率下界与未读取率上界。

**日志与开关**：复用现有 `persist.hiviewdfx.napiprofiler.enabled`、`ArkNativeEngine::napiProfilerEnabled` 及 NAPI 已链接的 `CountTraceEx`/`HITRACE_TAG_ACE`；固定名称的 HiTrace counters 承载检查点聚合，Hilog 只保留错误日志。不新增独立系统参数、HiSysEvent schema、日志文件、显示或 hidumper 命令。修正版见 `05-插桩patch.md`，并已同步 01/02/03 的交叉引用和统计口径。

## 审视结论更新

第 8、9、10 轮意见已闭环：后台 full-GC 样本只作低置信结构上界；Top13 61.47 MiB 已完成方法/构造器拆分和逐应用归属，最大贡献应用为 kuaishou；Kuaishou 已按 `24.035 MiB` 的方法闭包语义口径刷新 API26 前后台结构上界；第 7 轮插桩实现已由 7.0 Release 源码核查纠正为 Phase 1/Phase 2 方案；两种粒度及关键数据结构关系已落两份 DrawIO/SVG 架构图。当前插桩范围无遗留项，但 Phase 2 读取全路径覆盖仍是实施前置条件。

## 第 12 轮：正式实现改为最小 VM-owned recipe（2026-08-20）

**人工意见**：正式实现不得保留完整 `napi_property_descriptor[]`；按最小 owned recipe 修正所有相关设计、生命周期和收益口径。

**当前正式结论**：A2 + X1 采用最小 `NativeLazyMethodRecipe { method, data }`。64 位 ABI 下 payload 为 16 B、8 B 对齐，每个未物化槽独立分配；每类 `atomic<uintptr_t> slotDirectory[N]` 按 8 B/eligible slot 表达 `LAZY(recipe*) / MATERIALIZING(recipe*) / DONE / DEAD`；X1 `NapiLazyAccessor` 按设计 32 B/未物化槽计，最终类型仍需 ABI probe。`utf8name`、`napi_value name`、attributes、getter/setter/value 和 static 属性不进入 recipe：键和属性位已经进入 prototype 的 VM-owned `LayoutInfo`/`PropertyAttributes`，专用 lazy lookup 必须把当前 VM key 传入物化路径。禁止保存调用方数组、临时字符串和裸 handle；`data` 只复制非拥有指针值，资源释放仍由模块/既有协议负责。

每个 `LAZY(recipe*)` entry 独占一个 recipe allocator block；成功物化、覆盖或删除发布终态后立即释放该 block，directory 到全部终态、批量终止或 unload 时整体释放。正式净收益必须从未物化槽 avoided eager bytes 中扣除 32 B accessor、recipe allocator actual，再扣除按全部 eligible 槽 `N` 计的 8N B directory、每类 lifetime/registry/header 和实测 GC/物理内存成本。若剩余 avoided bytes 不再覆盖 live recipe actual、directory 与类固定成本，批量物化剩余槽并释放 directory/token；每类净收益不正则直接走即时路径。原“完整 descriptor 深拷贝 72–96 B/项”“连续 recipe + 1 B state”和“超过消除量 20% 切静态存储期”均标记为 **superseded**。

A1 不能复用 A2 的 16 B recipe，因为类粒度首次读取前尚无 prototype/LayoutInfo；A1 的完整类 recipe、模块注册契约和成本另行评审，本轮正式实现固定 A2。

Kuaishou strict A2 证据已重生为 schema v4。下表的“乐观中间值”只按 16 B logical recipe payload 扣费，不含独立 allocation 的 usable-size/metadata，也不含每类 lifetime/registry/header、GC 和 RSS/PSS，不能称为最终净收益；最终 break-even 同样不可用。

| schema v4 指标 | 前台 Kuaishou | 后台 full-GC Kuaishou |
|---|---:|---:|
| 结构候选 prototype / eligible slots | 70 / 463 | 75 / 576 |
| 闭包 + JSNativePointer + NapiFunctionInfo 毛收益 | 99,464–103,168 B | 122,560–127,168 B |
| 32 B accessor | 14,816 B | 18,432 B |
| 16 B logical recipe payload | 7,408 B | 9,216 B |
| 8 B/slot tagged directory | 3,704 B | 4,608 B |
| 乐观中间 savings（仅按 16 B payload） | 73,536–77,240 B | 90,304–94,912 B |
| recipe allocator actual / class fixed overhead | 未实测 | 未实测 |
| 最终净收益 / break-even | 不可计算 | 不可计算 |

## 第 11 轮：人工意见（2026-08-20，背景补写 InternalAccessor）

**人工意见**：结合真实的示例代码，在背景中解释介绍 InternalAccessor 的作用（配套 `06-NAPI-Prototype-Native方法按需绑定设计方案.md`）。

**闭环结论**：01-背景 §5 重写为三个小节——§5.1 对象布局（`accessor_data.h:29-46` 真实定义：24 B、getter/setter 裸函数指针、native 字段不进 GC 扫描）；§5.2 以 Date 为例的完整生命周期，四段真实源码（安装 `builtins.cpp:1078-1087`、分发 `object_fast_operator-inl.h:1080-1082`、回调与物化 `builtins_lazy_callback.cpp:23-36`）配 JS 侧首读/再读行为；§5.3 对本方案的复用边界（范式与分发骨架可复用；身份模型 D1 与写回路径 D2 不可平移，链接 06 §2.3/§3.3/§4.3）。参考文档补 06 链接。既有结论与口径不变。

## 第 13 轮：C1 简化架构与总体流程可读性审视（2026-08-24）

**审视范围**：`03-方案设计.md` 的 C1 直接 strong-reference 设计、总体流程图及其与第 6、10、12 轮已归档结论的一致性。

### 结论

C1 不可作为无条件实现结论。它可以保留为降低常驻元数据的候选，但必须先通过 GC 类型、key-aware 读取分发、环境卸载和 IC 写回四项准入验证；任一项失败时采用第 12 轮固定的 C2（最小 VM-owned recipe + slot directory + lifetime guard）或保持 eager。

### 主要问题

| 优先级 | 问题 | 依据 | 处理结论 |
|---|---|---|---|
| 阻塞 | C1 把 `JSNativePointer` 放入拟新增 `InternalAccessor` subtype 的 tagged 字段，却尚未证明该 subtype 的 visitor、verifier、dump 和 snapshot 全链路可用。 | 第 6、11 轮确认现有 `InternalAccessor` 是裸函数指针布局，native 字段不参与 GC 扫描。 | C1 需要独立 GC 类型 PoC；不能证明则使用 C2，禁止保存裸 native/handle。 |
| 阻塞 | `CallInternalGet` 当前不携带 property key；C1 需要 key 才能以 VM String 创建函数名。 | 第 6 轮已确认现有函数签名限制；本轮正文 §6.1 也记录此缺口。 | 必须覆盖解释器、IC、AOT 与 descriptor 读取路径并证明统一汇聚；否则使用 C2 的外置 recipe。 |
| 高 | C1 声称不需要 registry、generation 或 guard，但没有证明未物化槽在环境卸载、slot 覆盖/删除和 GC 交错时仍能安全终结。 | 第 10、12 轮已将 lifecycle guard 和终态管理作为 Release 基线的一部分。 | C1 必须完成未物化/已物化/覆盖/删除/卸载组合验证；失败转 C2。 |
| 高 | 只替换 slot value 不能保证旧 prototype IC handler 失效。 | 第 6 轮已要求走既有原型变更通知链；本轮 C1 仍需实测 listener 与 MegaIC。 | `NotifyAccessorChanged` 的实际覆盖范围必须以热 IC 用例验证，不得以名称推断。 |

### 可读性修订

- `03` 的总体流程为自上而下的 10 节点主闭环；最长节点标签限制为 37 字符。
- eager 回退、语义边界、IC 规则和延迟对象在图下表表达；失败与属性分支由后续章节表达。
- 既有 `napi-lazy-binding-target-architecture.svg` 含 22 个文本块并包含 token/guard 模型，不作为本节替换图。

### 方案比较

| 方案 | 收益来源 | 主要成本与风险 | 评审定位 |
|---|---|---|---|
| C1：直接 strong reference | 不创建 `JSFunction`、函数名 String；不常驻 recipe/directory。 | 新 GC subtype、全读取路径传 key、卸载安全均待证明。 | 有闸门的候选。 |
| C2：最小 VM-owned recipe | 同样延迟函数对象；复用现有 accessor 分发和明确的终态管理。 | recipe、directory、guard 的常驻成本会抵扣收益。 | 已归档的实现基线。 |
| C3：eager | 无延迟访问与新生命周期成本。 | 不减少启动期函数对象。 | 兼容性和收益下限基线。 |

### 闭环要求

1. 用目标 Release 源码完成 C1 的 GC subtype 和 key-aware 分发 PoC。
2. 对 C1 与 C2 以相同 bundle、操作序列和 allocator actual 复测净收益及首读 P50/P95/P99。
3. 覆盖热 IC、minor/full/compact GC、slot 覆盖/删除和环境销毁；其中任何一项不通过即停止 C1。

## 第 14 轮：C1 阻塞点目标 Release 源码核验（2026-08-24）

**核验基线**：`arkcompiler_ets_runtime@f04900cf951c66c2ea18b2bab5b591d5336c34b9`。

### 源码事实

| 核验项 | 源码事实 | 对 C1 的影响 |
|---|---|---|
| strong reference 载体 | `ecmascript/accessor_data.h` 中 `InternalAccessor` 为 `final`，仅含 getter/setter 两个 native 函数指针，并以 `DECL_VISIT_NATIVE_FIELD` 标注；`object_factory.cpp:2839-2848` 的 `NewInternalAccessor` 只分配既有 `InternalAccessorClass` 并写入这两个裸指针。 | 不能在现有对象中保存 GC 强引用的 `JSNativePointer`；继承扩字段与复用 factory 均不可行。 |
| property key | `ObjectFastOperator::CallGetter` 的签名仅含 `(thread, receiver, holder, value)`，其 internal 分支调用 `CallInternalGet(thread, objHandle)`；`JSObject::GetProperty` 慢路径可从 `ObjectOperator::GetKey()` 取得 key，但调用同样不传 key。 | C1 不能只新增 `CallInternalGet` 参数；fast operator 上游、慢路径和所有编译入口都必须传递已定位 key，或提供能识别当前 lazy slot 的专用分发。 |
| prototype 失效 | `js_hclass-inl.h:382-424` 的 `MarkProtoChanged` 只设置当前 HClass marker；`NoticeThroughChain` 才递归通知 prototype listener。 | 原槽写回至少要走 `NoticeThroughChain`；只调用 `MarkProtoChanged` 不足以证明依赖 prototype 的 IC 已失效。 |
| 生命周期 | 现有 `InternalAccessor` 不保存 per-slot owned metadata；本轮未找到可将未物化 slot 与 environment teardown、覆盖、删除统一终结的既有协议。 | C1 的"无 registry/guard/cleanup"没有 Release 源码依据；不能作为生命周期实现。 |

### 可解性判断

| 阻塞点 | 是否可通过工程改动解决 | 结论 |
|---|---|---|
| GC strong reference | 可新增独立 `JSType`、factory、visitor、verifier、dump 与 snapshot 支持。 | 这不再是 C1 的小范围 accessor 改动，且需要专用读取分发；实现形态收敛为 C2。 |
| key-aware 首读 | 可扩展 fast operator 及慢路径的调用契约，或让专用 lazy 分发取得当前 lazy slot 后定位 key。 | 需要解释器、IC、AOT、descriptor 与反射入口的完整覆盖验证；C1 不能保持现状。 |
| IC 失效 | 可复用 `NoticeThroughChain`。 | 需要通过热 LoadIC、StoreIC 与 MegaIC 用例验证；不能仅以 API 存在作为闭环。 |
| 卸载与终态 | 可由 slot directory、guard、`DEAD` 终态和 cleanup 协议解决。 | 这正是 C2 的 lifetime 模型；C1 的无 guard 约束不可保留。 |

### 审视结论

C1 不能在其既定约束下解决阻塞点，因此不进入开发。技术上可通过新增专用 lazy 对象、key-aware 分发、prototype 通知和生命周期协议实现按需绑定，但这些构成 C2 的 VM-owned recipe 方案，而非 C1 的直接 strong-reference 方案。

C2 仍有四项实施前置验证：全读取入口 key 传递或 slot 定位、`NoticeThroughChain` 后的热 IC 行为、新对象 GC/snapshot 全链路、environment cleanup 与 `DEAD` 竞态。任一项不通过时保持 eager。

## 第 15 轮：仅堆外分量方向核验（2026-08-24）

### 审视诉求

在 C2（堆内 + 堆外全量惰性）与 C3（eager）之间寻找一个只作用于堆外 `NapiFunctionInfo`、修改面更小的独立方向，评估其可行性与收益上限。

### 源码事实

| 核验项 | 源码事实 | 结论影响 |
|---|---|---|
| 堆外结构尺寸 | `native_value.h:54-63` 的 `NapiFunctionInfo` 含 `callback`、`data`、`isSendable`、`env`，容器场景另有 `scopeId`；合计 32 B / 40 B，每函数一次独立 `new`。 | 堆外分量按方法 447,707 个计为 13.663–17.079 MiB。 |
| 元数据来源 | `callback` 与 `data` 来自调用方 `napi_property_descriptor`，NAPI 不保证该数组在 `napi_define_class` 返回后存活。 | 这 16 B 必须在注册期复制保留，不能延迟到首次访问或首次调用；严格的"堆外惰性"不成立。 |
| 消费点集合 | 解引用点仅五处：`ark_native_engine.cpp:1180-1188`、`native_api.cpp:1402-1405`、`native_api.cpp:1281-1284`、`ark_native_engine.cpp:422-424`、`ark_native_engine.cpp:1440-1446`，全部位于 `arkui_napi` 内。 | 结构体可在不动公开 ABI 的前提下替换为按类连续分配的回调表。 |
| `scopeId` 消费条件 | `native_api.cpp:1280` 的读取被 `if (!function->IsConcurrentFunction(vm))` 保护，而目标两条创建路径均以 `Concurrent::YES` 建立函数（`jsnapi_expo.cpp:3668`、`3754`）。 | `scopeId` 可按类共享，无需每方法保存。 |
| extra info 空闲字段 | `JSFunction::SetFunctionExtraInfo`（`js_function.cpp:1072-1080`）把 `nativeFunc` 写入 `JSNativePointer::ExternalPointer`；`NewConcurrentWithName` 与 `NewConcurrentClassFunctionWithName` 传入 `nullptr`，`NewConcurrent` 传入实际函数指针。 | prototype 方法与 constructor 路径的 `ExternalPointer` 空闲，可承载表基址；`napi_create_function` 路径不可，故排除在范围外。 |
| 释放契约 | `JSNativePointer::DeleteExternalPointer`（`js_native_pointer.cpp:43-51`）已把 `externalPointer` 与 `data` 同时交给 deleter，`CommonDeleter` 签名匹配。 | 引用计数递减无需新增运行时接口。 |

### 可行性判断

| 子方向 | 判断 |
|---|---|
| 堆外真正惰性（首次访问或首次调用时才分配） | 不成立。`callback` 与 `data` 在注册期后不可再次获得。 |
| 按类连续分配回调表（E1 主方案） | 可行。每方法 16–24 B 取代 32–40 B 独立分配，同时消除 44 万次独立分配的记账开销。 |
| 保留 `NapiFunctionInfo` 并延迟到首次调用重建 | 否决。已调用方法同时占用 Entry 与 `NapiFunctionInfo`，总量高于主方案。 |
| 仅换分配器、结构体不动 | 否决。结构性收益为零，生命周期复杂度与主方案相同。 |

### 审视结论

存在一个与 C2 正交的独立方向 E1：属性槽语义、属性查找路径、IC 失效与 GC visitor 全部不改，只把堆外回调元数据由每方法独立分配收敛为按类一次连续分配。C2 的四项未决闸门中，key 传递、热 IC 与 GC 三项在 E1 下不存在。

E1 可比口径收益为 3.4–10.2 MiB（对应 Bucket C 方法分量 447,707 个，浅层字节数，不等于 committed/RSS/PSS），显著低于 C2 的 61.474 MiB 堆内目标上界。两者作用于不同分量，可叠加，E1 可独立先行。

E1 有两项准入前提未核验：目标路径 `ExternalPointer` 的读取侧是否确实无其他消费者，以及 `NapiFunctionInfo` 是否无跨仓使用者。设计与完整闸门清单见 [07-堆外回调元数据压缩方案.md](07-堆外回调元数据压缩方案.md)。

