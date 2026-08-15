# 审视日志（Native Interop 闭包惰性原型绑定）

本文档独立保存 5 轮不同角色审视记录与闭环意见，不混入正式方案文档。审视对象：01-背景 / 02-需求 / 03-方案设计。

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

**闭环结论**：01/02/03 已按本轮更新（§4.4 IC 失效机制、§4.5 descriptor 驻留量化、§4.6 插桩形态区分；需求 §4 新增两项风险）。插桩里程碑不变，仍是选型与立项前置。无遗留问题。

## 第 7 轮：人工审视 TODO 闭环（插桩 patch）

**人工意见**：「给出插桩统计『从未被读取的方法占比』的 patch 改动，以便人工进行插桩统计。」

**闭环结论**：新增 `05-插桩patch.md`——四个打点：创建侧登记（`NapiNativeCreateFunction`）、调用侧标记（native 回调 wrapper）、读取侧标记（`JSObject::GetProperty:1396` 慢路径，descriptor 形态经 `GetOwnPropertyDescriptor` 单列）、类实例化标记（`napi_new_instance:1512`）；输出含 `neverCalledNeverRead`（A2 折算）、`wholeClassUntouched`（A1 折算）、`bucketC_closures`（期望节省）与首用时序。01-背景 §6 已链接。

## 审视结论汇总

前 5 轮 8 项意见全部闭环；第 6 轮独立复核 6 项（链路核验、机制核验、IC 失效具体化、descriptor 成本量化、插桩形态细化、尺寸口径确认），已同步落稿。无遗留问题。