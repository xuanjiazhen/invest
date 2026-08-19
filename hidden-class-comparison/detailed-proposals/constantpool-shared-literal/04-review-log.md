# 审视日志（对象字面量外置 Backing COW）

审视对象：`01-背景.md`、`02-需求.md`、`03-方案设计.md`、`05-插桩patch.md`。当前范围只包含对象字面量外置 backing COW。

## 第 1 轮：范围收敛

| 原方向 | 当前处置 | 原因 |
|---|---|---|
| ConstantPool 字符串跨 VM 共享 | 移出本方案 | 依赖 worker/abc 重叠、shared heap、并发 intern 与 hash 生命周期，和对象字面量 COW 没有共同交付边界 |
| 数组字面量 COW | 不改 | ArkVM 已有小数组 COW；仅作为代码参照，不计入收益 |
| 对象字面量 HClass 跨 VM 共享 | 移出 | 收益仅数 KB/VM，且引入堆归属约束 |
| 模板克隆、编译期预填充 | 移出 | 属独立时间优化，不能与 backing COW 混算 |
| 对象字面量外置 backing COW | 保留 | 当前 `CloneObjectLiteral` 对 backing 深拷贝，存在可独立验证的 COW 改造点 |

结论：正文已删除子方向 A/B 结构、worker/shared-string 设计和混合收益，只保留对象字面量 COW。

## 第 2 轮：VM / 编译器审视

### 发现 1：不能共享需实例化重绑的函数槽

`ObjectFactory::CloneProperties(old, env, obj)` 和 compiler stub 会克隆 `JSFunction`，设置每个实例自己的 `LexicalEnv` / `HomeObject`（`object_factory.cpp:603-629`；`compiler/new_object_stub_builder.cpp:274-291`）。若直接共享这类 backing，会改变方法、`super` 和闭包语义。

**闭环**：首版 eligibility 排除含 `JSFunction` / `AccessorData` 的 backing，保留原深拷贝。inline 函数/访问器继续逐实例处理。

### 发现 2：只改 CloneObjectLiteral 不成立

普通 `JSObject` 的 properties/elements 写散布在属性写入、删除、扩容、dictionary 转换和 elements-kind migration 中；现有 COW 检查主要服务 `JSArray`。共享后若任一写路径直接修改 `TaggedArray`，会污染模板和其他实例。

**闭环**：方案新增 owner-aware 写前脱离语义，并将 runtime、IC store、stub、AOT、转换和 DFX 直接写路径列为完整性门槛。禁止在无 owner 的 `TaggedArray::Set` 内隐式复制。

### 发现 3：Runtime 与 compiler 有三条克隆实现

基础 runtime、带 env runtime 和 compiler stub 都实现了对象字面量克隆，不能只修改其中之一。

**闭环**：三条路径纳入同一 eligibility 与 fallback 规则；解释态、AOT 与 stub 必须对拍。

## 第 3 轮：GC / 内存审视

现有 `COWTaggedArray` 在 NON_MOVABLE 空间分配。减少 young-space clone backing 不必然降低 Region committed 或 RSS/PSS，反而可能增加 NON_MOVABLE 碎片。首次写时还会同时短暂存活共享 backing 与新 mutable backing。

**闭环**：收益拆分为事件累计、full-GC shallow、Region used/committed、RSS/PSS 和峰值；阈值由对象字面量专项插桩决定，物理收益必须 clean A/B 验证，且敏感性范围包含零。

## 第 4 轮：数据审视

Kuaishou API26 配对快照中的 ConstantPool 直接 target 数据为：

| 指标 | 前台 | 后台 full-GC |
|---|---:|---:|
| CP 直接持有 `JSObject` | 8,291 | 8,160 |
| CP 直接持有 `JSArray` | 8,534 | 8,530 |
| JSObject+JSArray target/backing 混合驻留域 | 1.309 MiB | 1.274 MiB |

冻结证据：`../../evidence/kuaishou-background-paired-census.json`。

该快照不记录对象字面量 clone 次数、来源、首次写率和脱离复制；backing 字节也把对象与数组合并。1.309/1.274 MiB 只能作为 ConstantPool 直接可见驻留域，不能作为对象字面量 COW 毛收益或净收益。

**闭环**：插桩删除 worker/字符串/数组统计，只输出对象字面量的 eligible/fallback、共享字节和首次写复制；无插桩数据时收益保持未量化。

## 第 5 轮：测试审视

普通对象不因本方案获得跨线程并发写语义。测试重点不是“两个线程同时写同一普通对象”，而是多个独立字面量实例共享初始 backing 后，各自首次写的隔离性。

**闭环**：DT 覆盖属性/元素首次写、删除、扩容、descriptor、symbol、dictionary、kind migration、方法/访问器回退、interpreter/AOT/stub、young/full GC 和开关回退。

## 当前结论

方案范围已收敛为对象字面量外置 backing COW，源码改造点成立，但收益仍依赖 clone/write 插桩。进入开发的前置条件是：

1. 写路径清单与 owner-aware 脱离设计完成评审；
2. 对象字面量专项插桩证明 `avoidedCloneBytes - detachCopyBytes > 0`；
3. clean A/B 方案能够单列 shallow、Region committed 和 RSS/PSS。

在这些条件满足前，方案可实现但不应默认开启，也不应承诺确定的内存收益。
