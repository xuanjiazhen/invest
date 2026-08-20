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

## 第 8 轮：Kuaishou 后台 full-GC 快照复核

**评估口径**：前台与后台 rawheap 使用同一 API 26 `rawheap_translator` 2.0.0 转换；后台为应用进入后台并执行全量 GC 后的独立存活堆。本轮只构造 A2 **结构候选上界**：HClass 无存活实例、prototype 直接持有非 `constructor` native-stub 方法、且闭包自身持有唯一 `JSNativePointer`。该条件不等价于“从未读取/调用”。冻结数据见 `evidence/kuaishou-background-paired-census.json`。

| 指标 | 前台 Kuaishou | 后台 full-GC Kuaishou | 后台相对前台 |
|---|---:|---:|---:|
| 结构候选 prototype / 方法槽 | 70 / 463 | 75 / 576 | +5 / +113 |
| 闭包 + JSNativePointer 浅层毛收益 | 84,648 B | 104,128 B | +19,480 B |
| `NapiFunctionInfo` 堆外模型 | 14,816–18,520 B | 18,432–23,040 B | +3,616–4,520 B |
| 毛收益合计 | 99,464–103,168 B（0.095–0.098 MiB） | 122,560–127,168 B（0.117–0.121 MiB） | +23,096–24,000 B |
| descriptor 驻留成本 | 33,336–44,448 B（0.032–0.042 MiB） | 41,472–55,296 B（0.040–0.053 MiB） | +8,136–10,848 B |
| 结构上界净收益 | 55,016–69,832 B（0.052–0.067 MiB） | 67,264–85,696 B（0.064–0.082 MiB） | +12,248–15,864 B |

**结论**：后台结构候选上界比前台高，但这反映两个采样时点的存活结构差异，不能解释为 full-GC 使真实收益增加。full-GC 只确认这些 prototype/闭包在后台采集时仍存活；它不记录属性是否曾读取、方法是否曾调用、descriptor 形态读取，也不覆盖 A1 整类未触及率。**原结论不变：A1/A2 选型与立项仍必须以前置插桩为准；本轮 0.064–0.082 MiB 只作低置信结构上界，不作承诺净收益。**另需通过实现 A/B 量化 allocator 碎片、IC 失效与 GC/RSS/PSS。

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

第 8 轮 `0.064–0.082 MiB` 则是上述方法闭包结构上界进一步限制为“闭包具有唯一可见 `JSNativePointer`”后，再计入 pointer、堆外 `NapiFunctionInfo` 和 descriptor 成本得到的 strict A2 净收益模型，不是方法闭包本体大小；两套数字不混用。

## 第 10 轮：7.0 Release 插桩可行性复核

**核验基线**：manifest `OpenHarmony-7.0-Release@4ad97323baf64f52922c5dadcbbd11754732a057`；`arkcompiler_ets_runtime@f04900cf951c66c2ea18b2bab5b591d5336c34b9`；`foundation/arkui/napi@464170c9c1faba39f56549a13d232d51740a49d3`。

**结论**：第 7 轮的 wrapper、`callbackPtr`、`JSObject::GetProperty` 单点读取、`napi_new_instance` 实例化标记和自定义 TSV 均不可作为 7.0 Release 实施 patch。`ArkNativeFunctionCallBack` 已通过 `runtimeInfo->GetData()` 获取真实 `NapiFunctionInfo`，应以 `NapiFunctionInfo *` 作为外置 registry entry 的活跃键，不修改其布局、不包装原 callback；属性读取必须覆盖解释器快路径、IC、compiler/AOT 和 descriptor/反射路径，未闭合前只能报告 Phase 1 callback 调用率下界与未读取率上界。

**日志与开关**：复用现有 `persist.hiviewdfx.napiprofiler.enabled`、`ArkNativeEngine::napiProfilerEnabled` 及 NAPI 已链接的 `CountTraceEx`/`HITRACE_TAG_ACE`；固定名称的 HiTrace counters 承载检查点聚合，Hilog 只保留错误日志。不新增独立系统参数、HiSysEvent schema、日志文件、显示或 hidumper 命令。修正版见 `05-插桩patch.md`，并已同步 01/02/03 的交叉引用和统计口径。

## 审视结论更新

第 8、9、10 轮意见已闭环：后台 full-GC 样本只作低置信结构上界；Top13 61.47 MiB 已完成方法/构造器拆分和逐应用归属，最大贡献应用为 kuaishou；Kuaishou 已按 `24.035 MiB` 的方法闭包语义口径刷新 API26 前后台结构上界；第 7 轮插桩实现已由 7.0 Release 源码核查纠正为 Phase 1/Phase 2 方案；两种粒度及关键数据结构关系已落两份 DrawIO/SVG 架构图。当前插桩范围无遗留项，但 Phase 2 读取全路径覆盖仍是实施前置条件。

## 第 11 轮：人工意见（2026-08-20，背景补写 InternalAccessor）

**人工意见**：结合真实的示例代码，在背景中解释介绍 InternalAccessor 的作用（配套 `06-InternalAccessor迁移NAPI设计评审.md`）。

**闭环结论**：01-背景 §5 重写为三个小节——§5.1 对象布局（`accessor_data.h:29-46` 真实定义：24 B、getter/setter 裸函数指针、native 字段不进 GC 扫描）；§5.2 以 Date 为例的完整生命周期，四段真实源码（安装 `builtins.cpp:1078-1087`、分发 `object_fast_operator-inl.h:1080-1082`、回调与物化 `builtins_lazy_callback.cpp:23-36`）配 JS 侧首读/再读行为；§5.3 对本方案的复用边界（范式与分发骨架可复用；身份模型 D1 与写回路径 D2 不可平移，链接 06 §2.3/§3.3/§4.3）。参考文档补 06 链接。既有结论与口径不变。
