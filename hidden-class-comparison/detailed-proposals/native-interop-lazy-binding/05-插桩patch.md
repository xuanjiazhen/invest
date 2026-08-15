# 插桩 Patch：native 方法「从未被读取占比」统计

目的：为 A1/A2 选型与收益折算提供两个比例——「整类未触及占比」与「单方法未读取占比」，并区分会强制 materialize 的 descriptor 形态读取。全部打点由系统参数 `persist.ark.propf.lazyprobe`（示例名）开关，关闭时零额外指令（分支预测友好），不改变任何语义。

## Patch 1：创建侧登记（NAPI 层）

**文件**：`foundation/arkui/napi/native_engine/impl/ark/ark_native_engine.cpp`

**位置**：`NapiNativeCreateFunction`（:190，方法/访问器创建的公共汇聚点）与 `NapiDefineClass`（:333，记录类名与 property_count）。

```cpp
// 新增头文件 napi_lazy_probe.h（本 patch 附带）
struct LazyProbeEntry {
    std::atomic<uint8_t> state;        // bit0 called, bit1 read, bit2 classTouched
    uint64_t createMs;
    const char* className;             // 静态字符串，模块 so 生命周期
    const char* methodName;
};
// 全局注册表：key = 原始 napi_callback 指针（同一 native 回调可对应多个方法名，用 (ptr, className, methodName) 三元组聚合）
CUnorderedMap<const void*, LazyProbeEntry*> g_lazyProbe;  // 进程级，创建期单线程，读取期只读

napi_value NapiNativeCreateFunction(...)  // :190 函数体首行：
    if (LazyProbe::Enabled()) {
        LazyProbe::Register(callback, className, name);  // 只登记，不分配 JS 堆对象
    }
```

## Patch 2：调用侧标记（包装 native 回调）

**文件**：同上 `NapiNativeCreateFunction`。

将传给 `FunctionRef::NewConcurrentWithName`（`jsnapi_expo.cpp:3947`）的回调包一层无捕获 wrapper：

```cpp
static napi_value ProbeWrapper(napi_env env, napi_callback_info info) {
    LazyProbe::Mark(info->callbackPtr, CALLED);   // atomic fetch_or，纳秒级
    return RealCallback(env, info);               // 尾调用原回调
}
// NapiNativeCreateFunction 内：callback = LazyProbe::Enabled() ? ProbeWrapper(real) : real;
```

同一 (ptr,class,method) 只需包装一次；wrapper 与原回调在注册表内互查。

## Patch 3：读取侧标记（区分值读取与 descriptor 形态）

**文件**：`arkcompiler/ets_runtime/ecmascript/js_object.cpp`

**位置**：`JSObject::GetProperty`（:1396，慢路径公共汇聚点；IC 命中路径不经过此处，首读必然走慢路径，满足「是否曾被读取」判定）。

```cpp
OperationResult JSObject::GetProperty(JSThread *thread, const JSHandle<JSTaggedValue> &key, bool hasSideEffect)
{
    // 函数体尾部、返回前：
    if (UNLIKELY(LazyProbe::Enabled()) && obj->GetJSHClass()->IsPrototype()) {
        JSTaggedValue res = <本次查找结果>;
        if (res.IsJSFunction()) {
            LazyProbe::MarkIfNativeMethod(res, READ);   // 查 JSFunction 的 extraInfo/nativePointer 是否命中注册表
        }
    }
    ...
}
```

descriptor 形态（`getOwnPropertyDescriptor`/`freeze`/序列化）经 `GetOwnPropertyDescriptor`（`js_object.cpp` 同文件）另加同类标记并记 `READ_AS_DESCRIPTOR` 单列——该形态在惰性方案中会强制 materialize，不能算作「真实使用」。

**热路径成本说明**：`LazyProbe::Enabled()` 为 false 时仅一次分支；true 时仅在 prototype 对象上多做一次结果类型判断，注册表查询以结果 JSFunction 的 native 指针为键（哈希一次）。

## Patch 4：类实例化标记

**文件**：`foundation/arkui/napi/native_api.cpp`

**位置**：`napi_new_instance`（:1512）。

```cpp
NAPI_EXTERN napi_status napi_new_instance(napi_env env, napi_value constructor, ...)
{
    // 入口：LazyProbe::Mark(constructor 的 native ctor ptr, CLASS_INSTANTIATED);
}
```

用于把「方法未读取」限定到「类零实例」（Bucket C 判定）与「类有实例」两个子集，避免高估。

## 输出

进程退出（`Runtime::Dispose` 或 hidumper 信号）时写出 TSV（hilog + 落盘 `/data/log/ark_lazy_probe_<pid>.tsv`）：

```text
# className  methodName  nClosure  called  read  readAsDescriptor  classInstantiated  firstCallMs  firstReadMs
Wsession     start       1         1       1     0                 1                  812          815
Wmedia       getSupport  1         0       0     0                 0                  -            -
```

汇总行输出四个决策数字：

```text
summary: methods=<N> neverCalledNeverRead=<x%> wholeClassUntouched=<y%>
         bucketC_closures=<count> descriptorFormOnly=<z%>
```

`neverCalledNeverRead`（方法粒度 A2 收益折算）与 `wholeClassUntouched`（类粒度 A1 收益折算）直接回填 02-需求 §2 的期望值；`bucketC_closures × 184 B` 为堆内期望节省。

## 场景与采样

三档各采一份：冷启动完成、主流程 5 min、后台驻留 30 min（对应 03-方案设计 §4.6）；`firstReadMs` 用于区分「采样后才首次使用」的时序偏差。
