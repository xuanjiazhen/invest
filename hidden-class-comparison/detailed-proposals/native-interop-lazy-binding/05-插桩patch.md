# 插桩 Patch：Native Interop 原型闭包使用率统计

## 1. 核查结论

原插桩不能直接实施，需按本文修正。主要问题如下。

1. `napi_callback_info` 不存在 `callbackPtr` 字段。7.0 Release 的原始回调和 `data` 位于 `NapiFunctionInfo`，`ArkNativeFunctionCallBack` 已通过 `runtimeInfo->GetData()` 取得该对象。
2. 不能用无捕获 `ProbeWrapper` 保存原回调和登记项，也无需包装。`ArkNativeFunctionCallBack` 已是普通 N-API 函数、prototype 方法和类构造器的调用汇聚点。
3. 不能以原始 `napi_callback` 指针为闭包实例键。同一回调可绑定到多个类、方法或属性；应以每个闭包独有的 `NapiFunctionInfo *` 作为活跃 registry entry 的键。
4. `JSObject::GetProperty` 不是首次属性读取的公共汇聚点。解释器快路径、LoadIC、compiler stub 和 AOT 代码可以直接从对象或 prototype 字段取值，不经过 `js_object.cpp:1396`。只在该点打桩会系统性漏报，并把已读取方法误判为未读取。
5. `napi_new_instance` 只覆盖 native 代码主动调用该 API 的构造，不覆盖 ArkTS/JS 的 `new`、`Reflect.construct` 等路径；历史“曾构造”也不等于采样时“零活实例”。Bucket C 必须在同一采样点通过 full-GC/rawheap 判断。
6. 不新增 `/data/log/ark_lazy_probe_*.tsv`、专用 hidumper 命令、显示页面、HiSysEvent schema 或新的系统参数。开关与输出复用 7.0 Release 已有 NAPI HiTrace 基础设施。

本 patch 分两阶段：

- Phase 1 可可靠测得 native callback 调用率和整类未调用率。调用前必然已取得函数，所以 `called` 是 `read` 的下界，`neverCalled` 是 `neverRead` 和惰性化收益的上界。Phase 1 只能用于封顶收益或排除收益不足的方案，不能冒充“从未读取占比”或直接给出期望收益。
- Phase 2 只有在属性读取全路径覆盖验证通过后，才可输出“方法未读取率”。原文的单点 `JSObject::GetProperty` patch 不属于可接受实现。

## 2. 核查基线

基于 manifest `OpenHarmony-7.0-Release@4ad97323baf64f52922c5dadcbbd11754732a057`，相关仓库冻结为：

| 仓库 | revision |
|---|---|
| `arkcompiler_ets_runtime` | `f04900cf951c66c2ea18b2bab5b591d5336c34b9` |
| `foundation_arkui_napi` | `464170c9c1faba39f56549a13d232d51740a49d3` |

源码锚点均指向上述 revision：

| 事实 | 源码锚点 |
|---|---|
| 创建普通 N-API 函数并分配 `NapiFunctionInfo` | `foundation/arkui/napi/native_engine/impl/ark/ark_native_engine.cpp:190-213` |
| 从 descriptor 创建 method/getter/setter | `foundation/arkui/napi/native_engine/impl/ark/ark_native_engine.cpp:216-247` |
| 类属性拆分为 static 与 prototype 属性 | `foundation/arkui/napi/native_engine/impl/ark/ark_native_engine.cpp:250-285` |
| `NapiDefineClass` 创建 constructor 的 `NapiFunctionInfo` | `foundation/arkui/napi/native_engine/impl/ark/ark_native_engine.cpp:333-369` |
| `NapiFunctionInfo` 真实字段 | `foundation/arkui/napi/native_engine/native_value.h:54-63` |
| native callback 公共汇聚点 | `foundation/arkui/napi/native_engine/impl/ark/ark_native_engine.cpp:1210-1281` |
| 现有 NAPI profiler trace | `foundation/arkui/napi/native_engine/impl/ark/ark_native_engine.cpp:1113-1207` |
| 现有 profiler 系统参数 | `foundation/arkui/napi/native_engine/impl/ark/ark_native_engine.cpp:3510-3527` |
| NAPI 已链接 HiTrace 并定义 `ENABLE_HITRACE` | `foundation/arkui/napi/BUILD.gn:158-173` |
| 现有 VM HiTrace counter 包装先例 | `arkcompiler/ets_runtime/ecmascript/ecma_macros.h:47-56` |
| VM 到 NAPI 原始回调的既有桥接 | `ark_native_engine.cpp:418-426`、`ecmascript/ecma_vm.h:593-610`、`ecmascript/napi/jsnapi_expo.cpp:6790-6793` |
| `JSObject::GetProperty` 仅是通用慢路径之一 | `arkcompiler/ets_runtime/ecmascript/js_object.cpp:1395-1463` |
| 解释器可直接走 `ObjectFastOperator` | `arkcompiler/ets_runtime/ecmascript/interpreter/fast_runtime_stub-inl.h:175-190` |
| IC 命中可直接从 handler 读字段 | `arkcompiler/ets_runtime/ecmascript/ic/ic_runtime_stub-inl.h:92-119,493-525` |
| compiler stub 生成独立 IC 快路径 | `arkcompiler/ets_runtime/ecmascript/compiler/common_stubs.cpp:1117-1158` |

## 3. 复用的 DFX 基础设施

### 3.1 开关

复用现有 `persist.hiviewdfx.napiprofiler.enabled`。7.0 Release 已在 `ArkNativeEngine::EnableNapiProfiler` 中读取该参数并设置 `ArkNativeEngine::napiProfilerEnabled`。该参数原本控制逐调用 HiTrace，本实验仅在同一 HiTrace 采集场景下附加内存聚合；不新增 `persist.ark.propf.lazyprobe` 或其他系统参数。

统计代码沿用现有 `#ifdef ENABLE_HITRACE` 编译边界，不新增专用编译宏。运行时参数关闭时不分配 state/entry、不复制名称、不发 counter；调用标记合并到已有 `napiProfilerEnabled` 条件内，不增加第二个运行时开关。

### 3.2 输出

复用已有 `hitrace:hitrace_meter` 的 `CountTraceEx`，使用 `HITRACE_TAG_ACE` 和固定 counter 名称。NAPI 在 `BUILD.gn:158-173` 已链接该组件并定义 `ENABLE_HITRACE`；ArkVM 也已有 `CountTraceEx` 包装先例（`ecmascript/ecma_macros.h:47-56`）。每个检查点发固定数量 counters，不逐方法输出名称。

建议 counter 名称：`NapiInteropCreatedCtor`、`NapiInteropCalledCtor`、`NapiInteropCreatedProtoMethod`、`NapiInteropCalledProtoMethod`、`NapiInteropWholeClassNeverCalled`。派生量 `neverCalled = created - called` 离线计算，不重复发 counter。

Hilog 只保留现有错误日志，不作为统计结果通道；不新增 HiSysEvent schema、TSV、hidumper 子命令或界面。HiSysEvent `STATISTIC` 适合长期设备遥测，但本任务是受控实验插桩，注册新事件 schema 会扩大改动和治理范围。`EcmaRuntimeStat` 是固定 runtime/builtin 调用 profiler，也不适合作为闭包集合统计载体。

### 3.3 采样触发

三档实验仍使用既有同步 full-GC/rawheap 工具链。测试驱动在冷启动完成、主流程 5 min、后台驻留 30 min 三个检查点分别执行以下动作：

1. 记录检查点并调用 engine 内部 `TraceNativeInteropUsageSummary()`，通过已有 `CountTraceEx`/`HITRACE_TAG_ACE` 发固定数量的累计聚合 counters；
2. 紧接着使用既有 `DumpHeapSnapshot`/rawheap 路径执行 full-GC 采样；
3. 离线报告以同一检查点的两类证据分别给出“历史调用上界/下界”和“full-GC 后存活 Bucket C”，不把二者伪装成可逐闭包直接 join 的同一张表。

helper 只由实验测试驱动调用，不挂入每次 heap dump，不增加外部命令。进程析构不发 counter、不写文件，也不依赖 `Runtime::Dispose`。

## 4. Phase 1：可直接实施的调用统计

### 4.1 状态归属

在 `ArkNativeEngine` 内持有当前 env 的 `std::shared_ptr<NativeInteropUsageState>`；仅 profiler 开启时创建 state，main VM、worker 和 context env 分别聚合。`NapiFunctionInfo` 布局保持不变，避免参数关闭时给每个 native 闭包永久增加 probe 指针。

新增一个仅在 `ENABLE_HITRACE` 下编译、仅在 profiler 开启时有 entry 的同步 registry：

```cpp
enum class InteropClosureKind : uint8_t {
    CONSTRUCTOR,
    PROTOTYPE_METHOD,
};

struct InteropProbeEntry {
    std::shared_ptr<NativeInteropUsageState> state;
    uint64_t classId;
    InteropClosureKind kind;
    bool called;
};

// key 是仍存活闭包独有的 NapiFunctionInfo *。
NativeInteropUsageRegistry::Register(info, entry);
NativeInteropUsageRegistry::MarkCalled(info);
NativeInteropUsageRegistry::TryUnregister(info);
```

registry 是进程生命周期的**所有权/路由表**，不是进程级聚合表：entry 以 `NapiFunctionInfo *` 唯一标识活跃闭包，内部 state 决定所属 env，统计输出只读取当前 engine 的 state。所有操作用同一互斥量保护；`TryUnregister` 在释放 `NapiFunctionInfo` 前移除 entry，允许地址后续复用。参数关闭时 registry 指针保持空，`TryUnregister` 直接返回，不创建 singleton、state、entry 或名称副本。

`NativeInteropUsageState` 保存按 classId 和 closure kind 的累计创建/调用计数，不保存业务类名、方法名或模块字符串裸指针。registry entry 持有 state 引用，允许 GC 延迟或并发执行 `CommonDeleter`；engine 释放 owner 引用后，最后一个 entry 再销毁 state，不反向解引用已析构的 `ArkNativeEngine *`。

getter/setter 与 data property 不纳入 native prototype 方法闭包主口径，另列 excluded 计数。constructor 必须单列；完整 Bucket C 是方法闭包与 constructor 的合计，不能只用方法分量命名 Bucket C。

### 4.2 创建侧登记

修改 `NapiDefineClass`、`NapiGetKeysAndAttrsFromProps` 和 `NapiNativeCreateFunction` 的内部参数传递，使创建侧知道 `classId`、static/prototype 属性位和 closure kind：

1. `NapiDefineClass` 在 profiler 开启时为该类分配 `classId`；`NapiCreateClassFunction` 成功返回后，以 constructor 的 `funcInfo` 注册 entry 并增加 `createdCtor`；
2. `NapiGetKeysAndAttrsFromProps` 已在 `attributes & NATIVE_STATIC` 处分离 static 与 prototype 属性，只有 `property.method != nullptr && !NATIVE_STATIC` 进入 `PROTOTYPE_METHOD`；
3. `NapiNativeCreateFunction` 创建 `FunctionRef` 成功后才以对应 `funcInfo` 注册 entry 并增加 `createdProtoMethod`，失败路径不得计入 `created`；
4. 同一 callback 被多个 descriptor 复用时会产生多个 `NapiFunctionInfo` 和 registry entry，因此按闭包实例分别计数；
5. `NapiDefineSendableClass` 保持原路径，不登记。

类名和方法名继续只供现有 Hitrace 使用。聚合统计不延长 `napi_property_descriptor` 字符串生命周期，也不改变 `FunctionRef::name`。

### 4.3 调用侧标记

在 `ArkNativeFunctionCallBack` 已取得 `NapiFunctionInfo *info`、`NativeEngine *engine` 且确认 engine 非空后，把标记合并进现有 profiler 分支，并放在调用原 callback 前：

```cpp
if (ArkNativeEngine::napiProfilerEnabled) {
    NativeInteropUsageRegistry::GetInstance().MarkCalled(info);
}
```

`MarkCalled()` 在同步 registry 中查找 `info`；未登记的普通 N-API 函数和排除项直接返回。首次命中时把 entry 的 `called` 置位，并更新其 state 中对应 classId/kind 的 `called` 聚合；后续调用不重复增加聚合。首次调用详细时序继续由既有 Hitrace 提供。

不修改 `info->callback`，不安装 wrapper，不访问不存在的 `napi_callback_info::callbackPtr`。参数关闭时复用现有 profiler 条件分支，不执行 registry 查找；参数开启时的互斥查表成本必须在实验报告中单列，不能据此评估正式惰性实现的稳态性能。

### 4.4 回收与并发

`CommonDeleter(void *env, void *externalPointer, void *data)` 的 `data` 正是 `NapiFunctionInfo *`。在现有 `delete info` 前调用 `NativeInteropUsageRegistry::TryUnregister(info)`；registry 未初始化或 info 未登记时直接返回。命中时移除 entry 并释放其 state 引用，无需通过 `env` 回查 engine，也不在 deleter 中写日志。

`JSNativePointer` 回收可进入异步或并发 native callback 队列，因此：

- registry 与 state 聚合更新必须线程安全；
- engine 进入 `RELEASING` 后停止注册新 entry；
- dump 对当前 engine state 取一致快照；
- registry entry 的 state 引用保证迟到 deleter 安全，不假设“创建期单线程、读取期只读”；
- registry 外壳采用 process-lifetime/no-destructor 持有，避免静态析构顺序与 task-pool deleter 竞争；VM teardown 后 entry 数必须为 0，进程结束时不主动遍历或输出。

Phase 1 输出的是当前 env 生命周期内的**累计创建/调用**，不是 GC 后仍存活闭包数。full-GC 后存活人口继续由 rawheap 统计，两个口径不得相减或相乘。

### 4.5 输出与边界

每个检查点使用固定名称发出以下 HiTrace counters：

```text
NapiInteropCreatedCtor=<N>
NapiInteropCalledCtor=<N>
NapiInteropCreatedProtoMethod=<N>
NapiInteropCalledProtoMethod=<N>
NapiInteropWholeClassNeverCalled=<N>
NapiInteropGetterSetterExcluded=<N>
NapiInteropStaticMethodExcluded=<N>
```

定义：

- `neverCalledProtoMethod = createdProtoMethod - calledProtoMethod`；
- `wholeClassNeverCalled`：该 classId 的 constructor 和所有 prototype method 在采样前均无 callback 调用；
- `called*` 是“至少调用一次”的闭包数，不是调用总次数；
- `calledProtoMethod / createdProtoMethod` 是方法读取率的下界；
- `neverCalledProtoMethod / createdProtoMethod` 是方法未读取率及 A2 收益比例的上界，不是期望值；
- `wholeClassNeverCalled` 是 A1“类导出从未读取”比例的上界，因为类可被读取、构造或反射检查而不执行任何 callback。

## 5. Phase 2：属性读取统计的准入条件

### 5.1 不采用的单点 patch

禁止只在 `JSObject::GetProperty` 或 LoadIC miss 打点。以下路径至少必须纳入同一识别协议：

1. 解释器 `GetPropertyByName/GetPropertyByValue` 快路径；
2. monomorphic/polymorphic/mega LoadIC handler 命中；
3. compiler common stub 和 AOT 内联字段读取；
4. prototype handler；
5. `GetOwnProperty`、`getOwnPropertyDescriptor(s)`、freeze/seal 等 descriptor 路径；
6. Proxy、Reflect、debugger 和序列化中会观察属性或 descriptor 的路径。

任一路径不能证明覆盖时，结果只能命名为 `observedRead`，不能计算 `neverRead = created - observedRead`。

### 5.2 跨层依赖边界

`ets_runtime` 不能 include `foundation/arkui/napi` 私有的 `NapiFunctionInfo`，否则形成反向依赖。7.0 Release 已有 `EcmaVM::NativePtrGetter`/`JSNApi::SetNativePtrGetter`，可从通用 VM DFX 代码把 `JSNativePointer::data` 还原为原始 callback；但原始 callback 不是闭包实例唯一键，因此该桥只能辅助识别 native function，不能直接更新 Phase 1 registry entry。

若实施 Phase 2，应在 `JSNApi`/`EcmaVM` 增加通用、编译期受控的 DFX callback：VM 在已证明覆盖的“返回属性值”位置传出 `JSNativePointer::data` 这一 opaque pointer；NAPI 注册 callback 后再解释为 `NapiFunctionInfo *` 并更新对应 registry entry。接口不得向 VM 暴露 NAPI 私有类型，不得在 VM 层建立 NAPI 专用 map，也不得新增日志通道。

该方案需要同时修改解释器和 compiler/AOT 生成路径，热路径影响显著，不应包含在 Phase 1 的 5-8 人日内。只有实验构建启用，正式产品构建必须在编译期移除 hook。

### 5.3 覆盖门槛

Phase 2 合入前必须用同一 prototype method 构造以下测试，并逐项确认 `read` 仅首次置位且不漏报：

| 读取方式 | 必测执行形态 |
|---|---|
| `proto.m` | 解释器快路径、IC miss、单态 IC、多态 IC、mega IC |
| 热循环 `proto.m` | AOT 开/关、PGO 开/关、JIT-free 产品配置 |
| `Reflect.get`/继承对象读取 | receiver 与 holder 不同、prototype handler |
| descriptor | `getOwnPropertyDescriptor(s)`、freeze、seal |
| 间接观察 | Proxy、debugger、序列化/枚举相关操作 |

覆盖测试未完成时，只能把 Phase 1 调用率作为读取率下界、未调用率作为未读取率上界，并结合相同检查点的 rawheap 证据封顶当前存量；不能把未调用比例直接回填为 A2 的未读取比例。

## 6. Bucket C 与收益折算

Bucket C 的判定必须在每个检查点完成 full-GC/rawheap 后执行：类在该快照中零活实例，且 prototype 关系可归属目标闭包。`napi_new_instance` 不参与零实例判定。

Phase 1/2 聚合与 rawheap 只共享采样检查点。现有快照不保证导出 `NapiFunctionInfo *` 或 probe ID，因此不得声称可逐闭包直接关联；若确需逐项 join，必须先验证同版 rawheap schema 已提供稳定标识，不能为本插桩另改快照格式。

输出必须分列：

- prototype 普通/命名方法闭包；
- constructor；
- 两者合计的完整 Bucket C。

不能固定乘 `184 B`。冻结证据中不同闭包类型的 `self_size` 不同，应从同次同版 heapsnapshot 逐对象求和。`self_size` 是浅层堆大小，不代表 committed、RSS 或 PSS；物理内存收益必须通过 clean A/B 测量。

## 7. 验收条件

1. 参数关闭时无 registry entry/state 分配、无 `NapiFunctionInfo` 布局变化、无名称复制、无统计 counter；
2. 参数开启时按类型满足 `created = called + neverCalled`；
3. 同一 callback 绑定多个方法时按闭包实例分别计数；
4. constructor 与 prototype method 分列，static/getter/setter/sendable 不混入口径；
5. main VM、worker、context env 相互隔离，异步/并发 deleter 无 UAF；
6. 不生成自定义 TSV、HiSysEvent schema、hidumper 命令或显示；每个检查点只发固定数量的 HiTrace counters，Hilog 不承载结果；
7. rawheap 与调用统计不做无稳定键的逐项 join，不把累计人口当成 GC 后存活人口；
8. Phase 2 全路径矩阵未通过前，报表不得给出 `neverRead` 或“未读取比例”结论。
