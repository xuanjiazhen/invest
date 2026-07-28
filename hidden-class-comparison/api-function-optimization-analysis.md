
## ENABLE_API_FUNCTION_OPTIMIZATION + ENABLE_MEMORY_OPTIMIZATION 路径分析

> 来源: OpenHarmony 源码 `js_function.h:230-260` 注释图 + 所有 `#if defined` 分支代码。
> 这两个宏均默认开启: `config.h:32` (`ENABLE_MEMORY_OPTIMIZATION=1`), `BUILD.gn:473` (`ENABLE_API_FUNCTION_OPTIMIZATION`).

---

### 1. 核心优化: JSApiFunction — 为 N-API 函数裁剪的瘦身版 JSFunction

源码直接提供了布局图 (`js_function.h:230-260`):

```
┌──────────────────────────┐
│ CodeEntryOrNativePointer │  ← JSFunctionBase
│ Length                   │
│ BitField                 │
├──────────────────────────┤  ← JSApiFunction (N-API 函数使用此类)
│ ProtoOrHClass            │      只到这里，省略以下所有 JIT 字段
│ LexicalEnv               │
│ HomeObject               │
├──────────────────────────┤  ← JSFunction (N-API 不需要以下字段)
│ RawProfileTypeInfo  (8B) │  ← IC feedback vector 指针 — 省略
│ MachineCode         (8B) │  ← JIT 编译产物 — 省略
│ BaselineCode        (8B) │  ← Baseline JIT — 省略
│ Module              (8B) │  ← ENABLE_MEMORY_OPTIMIZATION 下
│ WorkNodePointer     (8B) │  ← 无 ENABLE_MEMORY_OPTIMIZATION 时
└──────────────────────────┘
```

**每个 API 函数对象节省: 32B (MEMORY_OPTIMIZATION 下) 或 40B。**

80 method class → 节省 80×32B = **2.5 KB** 的 JSFunction 对象内存。

### 2. 两个层面的优化

#### 层面 1: HClass 模板 (类注册时)

```cpp
// jsnapi_class_creation_helper.cpp:156-160
#if defined(ENABLE_API_FUNCTION_OPTIMIZATION) && ENABLE_MEMORY_OPTIMIZATION
    JSHandle<JSHClass> functionClass = factory->CreateApiClassFuncHClass(thread, inlinedStaticPropCount);
    //                                    ^^^^^^^ 使用 JSApiFunction::SIZE 作为基础大小
#else
    JSHandle<JSHClass> functionClass = factory->CreateClassFuncHClass(thread, inlinedStaticPropCount);
    //                                    ^^^^^ 使用 JSFunction::SIZE 作为基础大小
#endif
```

`CreateApiClassFuncHClass` vs `CreateClassFuncHClass`:
```cpp
// object_factory.cpp:5909 vs 5902
CreateApiClassFuncHClass(..., JSApiFunction::SIZE, JSType::JS_API_FUNCTION, ...);
CreateClassFuncHClass  (..., JSFunction::SIZE,    JSType::JS_FUNCTION,      ...);
```

影响: HClass 的 `ObjectSizeInWords` 减小 → 每个 class 构造函数对象更小。

#### 层面 2: 函数创建 (每个 native method)

```cpp
// jsnapi_expo.cpp:3989-3993
#if defined(ENABLE_API_FUNCTION_OPTIMIZATION) && ENABLE_MEMORY_OPTIMIZATION
    JSHandle<JSHClass> hclass = JSHandle<JSHClass>::Cast(env->GetApiFunctionClassWithoutName());
    //                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 使用预构建的单例 HClass
    JSHandle<JSFunction> current =
        factory->NewConstructorJSApiFunctionByHClass(nativeFunc, hclass);
    //      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ 创建 JSApiFunction 子类对象
#else
    JSHandle<JSHClass> hclass = JSHandle<JSHClass>::Cast(env->GetFunctionClassWithoutName());
    JSHandle<JSFunction> current = factory->NewJSFunctionByHClass(
        nativeFunc, hclass, ecmascript::FunctionKind::CLASS_CONSTRUCTOR);
    //                     ^^^^^^^^^^^^^^^^^^^^^ 需要显式指定 CLASS_CONSTRUCTOR
#endif
```

### 3. 三处关键调用位置

| 函数 | 文件:行号 | 优化对象 |
|------|----------|---------|
| `CreateClassFuncWithProperties` | `jsnapi_class_creation_helper.cpp:156,181` | HClass 模板 + JSFunction |
| `NewClassFunction` | `jsnapi_expo.cpp:3989` | 类构造函数 |
| `NewConcurrentClassFunctionWithName` | `jsnapi_expo.cpp:4025` | 并发类构造函数 |
| `New` / `NewConcurrent` | `jsnapi_expo.cpp:3826,3855,3884` | 普通 API 函数 |

### 4. 配合 ENABLE_MEMORY_OPTIMIZATION 的额外节省

在 `builtins.cpp` 中 (`line 267-281, 735+`):
```cpp
#if ENABLE_MEMORY_OPTIMIZATION
    // 使用 OPTIMIZED_FUNCTION_CAPACITY_OF_IN_OBJECTS = 3 (vs 默认 4)
    JSHandle<JSHClass> functionClass = factory_->CreateFunctionClass(
        ..., JSHClass::OPTIMIZED_FUNCTION_CAPACITY_OF_IN_OBJECTS);
#endif
```

`js_hclass.h:418`: `OPTIMIZED_FUNCTION_CAPACITY_OF_IN_OBJECTS = 3`

减少 1 个默认 inline slot → HClass 减少 8B → 所有 Function 原型 HClass 节省 8B。

### 5. 对 NapiDefineClass 内存的量化影响

以 80 method class 为例:

```
                   无优化                    优化后                 节省
─────────────────────────────────────────────────────────────────────────
HClass 模板       JSFunction::SIZE           JSApiFunction::SIZE      8B/HClass
JSFunction 对象   80 × ~112B (全字段)       80 × ~80B (裁剪)         ~2.5 KB
Inline props      DEFAULT=4                  OPTIMIZED=3              ~8B/HClass
单例 HClass       每次创建新 HClass           GlobalEnv 预构建共享     ~120B/函数
Function extra    ProfileTypeInfo prealloc  不需要                    ~8B/函数
─────────────────────────────────────────────────────────────────────────
总计节省: ~30-40B/函数对象 + 减少 HClass 创建
```

### 6. 与 V8 的对照

V8 对 API 函数也有类似优化:
- `ApiFunction` vs `JSFunction` — 类似 JSApiFunction 的设计
- 惰性 IC feedback vector — 不预分配
- 共享 Map 单例 — `native_context()->function_map()`

ArkVM 的双宏路径实现了与 V8 类似的 API 函数裁剪机制。

### 7. 验证: 类型安全检查

```cpp
// js_function.h:477-483
bool IsNotJSApiFunction() const {
    return GetJSHClass()->GetObjectType() != JSType::JS_API_FUNCTION;
}
bool IsJSApiFunction() const {
    return GetJSHClass()->GetObjectType() == JSType::JS_API_FUNCTION;
}
```

通过 HClass 的 `JSType` 区分，确保裁剪后的对象不会被错误地访问 JIT 字段。`ACCESSORS_ASAN_CHECK` 宏在访问 `RawProfileTypeInfo` 等字段时会调用 `IsNotJSApiFunction()` 进行 ASAN 级别的运行时校验。
