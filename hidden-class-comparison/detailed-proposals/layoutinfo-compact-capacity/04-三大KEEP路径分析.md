# 三大 GROW→KEEP 转换路径：逐路径浪费分析与 V8 对照

本文档对 LayoutInfo 当前使用 `GrowMode::GROW` 的三条最大浪费候选路径进行源码级分析，包含代码示例、浪费可视化、性能模型和 V8 对照。GROW 的 +4 是容量单位：每次分配最多预留 4 个 property-capacity units（8 个 TaggedArray 槽位，64 B；接近 `MAX_PROPERTIES_LENGTH` 时被截断为更少）。实际浪费取决于后续追加，稳态浪费上界为 64 B。三条路径当前均标记为源码候选：属性数可知的依据已在源码核验，但对象群体的准确数量、属性闭包的完整性、后续追加概率需通过插桩验证后才能确定最终收益。

范围限定：本文仅分析 LocalHeap 的 `LayoutInfo`（`TaggedArray` 子类）。SharedHeap/Sendable 路径使用 `SLayoutInfo`（`shared_object_factory.cpp`、`CopyAndReSortSLayoutInfo` 等），有独立的并发与序列化约束，不在本文范围内。


## 目录

1. [全部 LayoutInfo 分配路径总览](#1-全部-layoutinfo-分配路径总览)
2. [路径 G1：函数 HClass LayoutInfo](#2-路径-g1函数-hclass-layoutinfo)
3. [路径 G10：字典→fast 迁移](#3-路径-g10字典fast-迁移)
4. [路径 G11：N-API/工厂大对象属性构造](#4-路径-g11n-api工厂大对象属性构造源码候选)
5. [汇总与结论](#5-汇总与结论)

---

## 1. 全部 LayoutInfo 分配路径总览

### 1.1 KEEP 精确分配（7 个路径）

| # | 调用点 | 创建什么 | 属性来源 |
|---|--------|---------|---------|
| K1 | `class_info_extractor.cpp:216` | 类 prototype LayoutInfo | abc 静态元数据 |
| K2 | `class_info_extractor.cpp:266` | 类 static LayoutInfo | abc 静态元数据 |
| K3 | `js_hclass.cpp:1495` | 对象字面量 root HClass | 编译期字面量属性列表 |
| K4 | `js_hclass.cpp:1526` | 对象字面量（另一路径） | 编译期 |
| K5 | `object_factory.cpp:2085` | 默认类 prototype HClass | 固定 schema |
| K6 | `object_factory.cpp:2105` | 默认类 prototype 变体 | 固定 schema |
| K7 | `global_env_constants.cpp:577` | 空 LayoutInfo（常量） | 0 属性 |

### 1.2 GROW +4 slack（12 个路径，每 LayoutInfo 最多浪费 64 B）

| # | 调用点 | 创建什么 | 典型属性数 | 浪费/Layout | 快照占比 |
|---|--------|---------|----------|-----------|---------|
| **G1** | `object_factory.cpp:2029-2075` 等 | **函数类 HClass LayoutInfo**（G1-A bootstrap / G1-B N-API 类函数 / G1-C N-API 类 prototype，见 §2.4a） | 2-3（G1-A）；按事务上界（G1-B/C） | **最多 80 B**（G1-A 两类分支） | 50% |
| G2 | `builtins.cpp:428` | 内建函数 LayoutInfo | 1-2 | 48-64 B | <1% |
| G3 | `builtins.cpp:553` | Function.prototype 属性 | 2-3 | 48-64 B | <1% |
| G4 | `builtins.cpp:586` | Function 静态属性 | 1-3 | 32-64 B | <1% |
| G5 | `js_array.cpp:970` | Array 函数类 LayoutInfo | 1 | 64 B | <1% |
| G6 | `js_array.cpp:1007` | Array prototype LayoutInfo | 1 | 64 B | <1% |
| G7 | `object_factory.cpp:882` | RegExp 类 LayoutInfo | 1 | 64 B | <1% |
| G8 | `object_factory.cpp:907` | Array length 属性 | 1 | 64 B | <1% |
| G9 | `object_factory.cpp:935` | Arguments length 属性 | 1 | 64 B | <1% |
| **G10** | `js_hclass.cpp:719-746` | **字典→fast 迁移**（named-property，`isDictionary=true`；elements 另见 G10-E） | N | **最多 64 B** | 15% |
| **G11** | `object_factory.cpp:5722,5829` | **N-API/工厂大对象属性构造**（G11-B direct，63<N≤1023，见 §4.1） | 64-1023 | **最多 64 B** | 10% |
| G12 | `object_factory.cpp:5423,4340` | Iterator/其他 | 2-N | 32-64 B | ~2% |

---

## 2. 路径 G1：函数类 HClass LayoutInfo（源码候选）

### 2.1 应用代码

注意：`CreateFunctionClass` 创建的是函数类 HClass（per-FunctionKind），不是每个 JSFunction 实例各自创建 LayoutInfo。内建函数实例通常通过 `GetHClassByFunctionKind` 复用环境中已有的 HClass（`object_factory.cpp:1929-1995`）。

```ts
// 每个模块的每个函数声明/表达式
export function add(a: number, b: number): number { return a + b; }
export const multiply = (x: number) => x * 2;
export class Calculator { /* ... */ }
```

### 2.2 VM 内部执行

```cpp
// object_factory.cpp:2029-2075 — CreateFunctionClass
// 创建函数类 HClass 及其 LayoutInfo（per-FunctionKind，非 per-function）
uint32_t fieldOrder = 0;

// LayoutInfo 创建参数依赖 inlinedProps：
// JSFunction::LENGTH_OF_INLINE_PROPERTIES = 3（js_function.h:258）
// 对应 length / name / prototype 三个内联属性槽位
if (inlinedProps == JSHClass::DEFAULT_CAPACITY_OF_IN_OBJECTS) {
    layoutInfoHandle = CreateLayoutInfo(JSFunction::LENGTH_OF_INLINE_PROPERTIES);
    //             ↑ CreateLayoutInfo(3, SEMI, GROW)
    //             → ComputeGrowCapacity(3) = 3 + 4 = 7
} else {
    layoutInfoHandle = CreateLayoutInfo(static_cast<int>(inlinedProps));
    //             → capacity = inlinedProps + 4（同样 GROW）
}
// GrowMode 默认 GROW → capacity = N + 4

// 属性写入闭包依赖 FunctionKind（object_factory.cpp:2039-2075）：
// ① length：所有 kind 都写入
layoutInfoHandle->AddKey(thread_, 0, "length", attributes);

// ② name：非 class constructor 才写入
if (!JSFunction::IsClassConstructor(kind)) {
    layoutInfoHandle->AddKey(thread_, 1, "name", attributes);
}

// ③ prototype：两个写入分支
//    a) HasPrototype(kind) 且非 class constructor
//    b) class / derived constructor（else-if，同样写 prototype）
if (JSFunction::HasPrototype(kind) && !JSFunction::IsClassConstructor(kind)) {
    layoutInfoHandle->AddKey(thread_, ..., "prototype", attributes);
} else if (JSFunction::IsClassConstructor(kind)) {
    layoutInfoHandle->AddKey(thread_, ..., "prototype", attributes);
}
// HasPrototype 范围：BASE_CONSTRUCTOR..ASYNC_GENERATOR_FUNCTION，
// 排除 BUILTIN_PROXY_CONSTRUCTOR（js_function.h:381-385）；
// NORMAL_FUNCTION=0（js_function_kind.h:23）不在范围内——不写 prototype
```

### 2.3 浪费可视化（按 FunctionKind 分支）

`CreateFunctionClass` 内部的写入集合由 FunctionKind 决定（`object_factory.cpp:2039-2075`）。`HasPrototype` 的实际范围是 `BASE_CONSTRUCTOR .. ASYNC_GENERATOR_FUNCTION`（排除 `BUILTIN_PROXY_CONSTRUCTOR`，`js_function.h:381-385`）；`NORMAL_FUNCTION=0`（`js_function_kind.h:23`）不在该范围内，不写 prototype。默认 requested=3、GROW capacity=7（128 B）下，创建后物理 slack 为：

| FunctionKind 分支 | CreateFunctionClass 内部写入 | 属性数 | slack units | slack 字节 |
|---|---|---:|---:|---:|
| 无 prototype 且非 class constructor（NORMAL/ARROW/GETTER/SETTER/ASYNC/CONCURRENT 等） | length + name | 2 | 5 | 80 B |
| 有 prototype 且非 class constructor（BASE_CONSTRUCTOR/BUILTIN_CONSTRUCTOR/GENERATOR/ASYNC_GENERATOR/NONE 等） | length + name + prototype | 3 | 4 | 64 B |
| class / derived constructor | length + prototype（不写 name） | 2 | 5 | 80 B |

以 3 属性分支（有 prototype 且非 class constructor）为例：

```text
LayoutInfo (capacity=7, self_size=16+16×7=128 B)
├─ slot[0-1]   length    (key+attr)  ← 有效
├─ slot[2-3]   name      (key+attr)  ← 有效
├─ slot[4-5]   prototype (key+attr)  ← 有效
├─ slot[6-13]  Hole ×4 属性位        ← ★ 最多 4 property-capacity units
                                        = 最多 8 tagged slots = 最多 64 B

KEEP 版本: capacity=3, self_size=64 B, 该分支创建期浪费=0
```


### 2.4 改为 KEEP 的性能分析

```cpp
// 修改后（1 行）
layoutInfoHandle = CreateLayoutInfo(JSFunction::LENGTH_OF_INLINE_PROPERTIES,
                                     MemSpaceType::SEMI_SPACE, GrowMode::KEEP);
// capacity = 3, self_size = 64 B
// 3 属性分支: length → name → prototype 三次 AddKey 恰好填满 cap=3
// 2 属性分支: 两次 AddKey 后余 1 槽位（16 B），无越界
```

| 维度 | 现有 GROW | 改为 KEEP | 差异 |
|------|----------|----------|------|
| 分配大小 | 128 B | 64 B | **-64 B** |
| 创建期 AddKey | ≤3 次（原地写） | ≤3 次（原地写） | **零** |
| 发布后追加属性 | 最多 5 个 slack 属性位内原地写（按分支 4-5） | capacity 已满或余 1，追加触发一次 Extend/CopyAndReSort | 见下方约束 |

**性能影响**：创建时的 AddKey 均为原地写入，行为不变。但该 HClass 被显式设置为可扩展（`object_factory.cpp:2022-2028`），且后续是否沿同一 LayoutInfo 追加取决于具体使用模式——需插桩确认“发布后无同 backing 追加”后才能从源码候选升级为确定性 KEEP。

### 2.4a G1 子路径拆分（G1-A / G1-B / G1-C）

G1 的调用者分三类，：

**G1-A：VM bootstrap/专用函数类 HClass**。`CreateFunctionClass` 直接调用，写入闭包即 §2.2/§2.3 的 FunctionKind 分支（2-3 属性）

**G1-B：N-API class function HClass**。用户入口 `FunctionRef::NewConcurrentClassFunctionWithName`（`jsnapi_expo.cpp:4044-4075`）→ `CreateClassFuncWithProperties`（`jsnapi_class_creation_helper.cpp:149-216`）→ `CreateClassFuncHClass`/`CreateApiClassFuncHClass`（`object_factory.cpp:5902/5909`）。容量参数：

```text
inlinedStaticPropCount = min(staticPropCount, maxInlPropCountForClassFunc)
inlinedProps = inlinedStaticPropCount + DEFAULT_CAPACITY_OF_IN_OBJECTS(4)
→ CreateFunctionClass(CLASS_CONSTRUCTOR, ..., inlinedProps)
→ GROW capacity = inlinedProps + 4 = inlinedStaticPropCount + 8
```

完整无 transition 写入闭包不止 `CreateFunctionClass` 内部的 length + prototype（class constructor 不写 name）：事务后续经 `AddInlinedPropToHClass` 写入 name 和成功进入 fast path 的静态属性（`jsnapi_class_creation_helper.cpp:161-179`）。最大安全写入数：

```text
max_write = 2 (length + prototype) + 1 (name) + inlinedStaticPropCount
          = 3 + inlinedStaticPropCount
KEEP(inlinedProps) 容量 = inlinedStaticPropCount + 4 = max_write + 1
```

特殊分支：`inlinedStaticPropCount=0` 时 `inlinedProps=4=DEFAULT_CAPACITY_OF_IN_OBJECTS`，`CreateFunctionClass` 内改走 `CreateLayoutInfo(LENGTH_OF_INLINE_PROPERTIES=3)`，事务完整写入 = length+prototype+name = 3，`KEEP(3)` 恰好安全；


### 2.5 V8 对照：函数 Map 创建

V8 的函数对象不独立创建 DescriptorArray——所有同种 FunctionKind 的函数共享 native context 缓存的同一个 Map（含同一个 DescriptorArray）。

**V8 的函数 Map 创建流程**（`src/heap/factory.cc`）：

```cpp
// Factory::NewFunction — 创建函数时不创建新 DescriptorArray
Handle<JSFunction> Factory::NewFunction(Handle<Map> map) {
    // map 来自 native_context->get(i) — 已缓存的共享 Map
    // DescriptorArray 已在 context 初始化时创建，此后不变
    JSFunction fn = NewJSObject(map);
    return fn;
}

// 初始化时每种 FunctionKind 只创建一次 Map：
//   native_context->set(ORDINARY_FUNCTION_INDEX, CreateFunctionMap(...))
//   → Factory::CreateFunctionMap → NewMap(JS_FUNCTION_TYPE, size, ...)
//     → Map 自带 DescriptorArray [length, name] — 精确 2 条，无 slack
//   此后所有 ordinary function 共享这一个 Map + DescriptorArray
```

**结构对比**：

| 维度 | V8 | ArkVM |
|------|-----|-------|
| 函数 Map/DescriptorArray 数量 | **per-context 每个 FunctionKind 一个**（~5 种 kind → ~5 个） | **per function HClass 一个**（数千到数万） |
| DescriptorArray 分配 | context 初始化时一次性创建，capacity=属性数（无 slack） | 每个函数创建时独立分配，GROW +4 slack |
| 后续属性追加 | 走 transition 链（`ShareDescriptor`），不修改共享数组 | 走 `AddPropertyToNewHClass`，可能原地追加 |
| waste | **零**（共享 + 无 slack） | 最多 64 B × 每个函数类 HClass |

**ArkVM 差异的根源**：ArkVM 为每个函数类 HClass 独立调用 `CreateLayoutInfo(LENGTH_OF_INLINE_PROPERTIES=3, GROW)`，而非从 GlobalEnv 缓存复用。V8 的做法等价于将此路径的 `GrowMode` 从 `GROW` 改为 `KEEP` 并加上 context 级共享。函数类 HClass 的创建次数取决于 VM 初始化和 FunctionKind 种类数，而非应用代码中的函数声明数。

---

## 3. 路径 G10：字典→fast 迁移（BUILD_EXACT_WITH_FALLBACK 候选）

### 3.1 应用代码

```ts
// 应用代码（动态属性操作导致字典退化，然后稳定）
const config: Record<string, number> = {};
config.alpha = 1;
config.beta = 2;
delete config.alpha;       // ← 触发字典模式
config.alpha = 1;          // ← 属性重新稳定
// ... VM 检测到对象稳定，迁移回 fast 模式
```

**两段归因**：`delete` 触发的是 `JSObject::TransitionToDictionary`（`js_object.cpp:185-244`），只将对象转入 dictionary mode，G10 仅在后续 `JSObject::OptimizeAsFastProperties`（`js_object.cpp:477-511`）命中 `isDictionary=true` 分支时发生。不能用 dictionary 对象数量直接替代 G10 调用次数。

### 3.2 VM 内部执行

```cpp
// js_hclass.cpp:719-746 — OptimizeAsFastProperties（named-property，isDictionary=true 分支）
int numberOfProperties = properties->EntriesCount();  // ← 属性数已知！
JSHandle<LayoutInfo> layoutInfoHandle = factory->CreateLayoutInfo(numberOfProperties);
//             ↑ CreateLayoutInfo(N, SEMI, GROW)
//             → capacity = N + 4

// 然后逐个填入 N 个属性
for (int i = 0; i < numberOfProperties; i++) {
    JSTaggedValue key = properties->GetKey(thread, indexOrder[i]);
    layoutInfoHandle->AddKey(thread_, i, key, attributes);
}
// 填完后 ExtraLength=N, capacity=N+4, slack=4 → 浪费最多 64 B
```

### 3.3 改为 KEEP 的性能分析

| 维度 | 现有 GROW | 改为 KEEP | 差异 |
|------|----------|----------|------|
| 迁移时的 N 次 AddKey | 原地写（cap=N+4） | 原地写（cap=N） | **零** |
| 迁移后追加属性 | 用 slack 原地写 | **触发一次 Extend** | 一次分配+拷贝+屏障（操作级，未实测） |

**劣化场景**（迁移后追加属性）：

```text
GROW 现状：
  cap=N+4 > N → 原地 AddKey

KEEP 改后：
  cap=N ≤ N → ExtendLayoutInfo
    → 分配新数组 cap=N+4（与 GROW 初始分配相同！）
    → 拷贝 2N 槽（N 属性 × 2 槽/属性）
    → AddKey
    代价 = 1 次分配 + 2N 槽拷贝 + 写屏障（操作级模型，未实测）
```


**实际风险评估**：字典→fast 迁移本身意味着 VM 判定该对象形状已稳定。迁移后再追加属性的概率极低（如果经常追加，VM 就不会迁移回 fast 了）。

### 3.4 V8 对照：字典→fast 迁移

V8 的 `JSObject::MigrateSlowToFast`（`src/objects/objects.cc`）在迁移时采用**精确容量 + 按需 slack** 策略。

**V8 迁移时的 DescriptorArray 分配**：

```cpp
// objects.cc — MigrateSlowToFast 核心路径
void JSObject::MigrateSlowToFast(...) {
    int nof = dictionary->NumberOfElements();  // 属性数已知

    // 分配新 DescriptorArray — slack 参数显式传 0
    Handle<DescriptorArray> new_descriptors =
        DescriptorArray::Allocate(isolate, nof, 0, AllocationType::kYoung);
    //                                    ↑   ↑
    //                              nof 个描述符  slack = 0（精确！）
    
    // 逐条填入
    for (int i = 0; i < nof; i++) {
        new_descriptors->Set(i, descriptors->Get(i));
    }
}
```

**V8 后续追加的处理**：迁移后如有新属性追加，走 `Map::TransitionToDataProperty` → `ShareDescriptor` → `EnsureDescriptorSlack(map, SlackForArraySize(old_size))`——使用条件性 slack（小数组 +1、大数组 +25%），而非固定 +4。

**结构对比**：

| 维度 | V8 | ArkVM |
|------|-----|-------|
| 迁移时 capacity | `nof + 0`（精确） | `nof + 4`（GROW） |
| 迁移时 waste | **零** | 64 B |
| 迁移后追加 | `ShareDescriptor` + `SlackForArraySize`（条件性） | `ExtendLayoutInfo` + 固定 +4 |
| GC 回收 | `TrimDescriptorArray` 物理右裁剪回收超量 slack | 无回收机制 |

**结论**：V8 在此路径已采用精确容量（slack=0），与 KEEP 等效。ArkVM 改 KEEP 后行为与 V8 对齐。

---

## 4. 路径 G11：N-API/工厂大对象属性构造（源码候选）

### 4.1 子路径拆分（G11-A / G11-B / G11-C）

用户入口为 `ObjectRef::NewWithProperties` / `NewWithNamedProperties`（`jsnapi_expo.cpp:2815-2848`、`2864-2873`）。按 `propertyCount` 阈值分流（`MAX_LITERAL_HCLASS_CACHE_SIZE=63`、`MAX_FAST_PROPS_CAPACITY=1023`，`property_attributes.h:97-105`）：

| 子路径 | 条件 | 源码路径 | 是否 direct LayoutInfo 分配 |
|---|---|---|---|
| G11-A 小对象 | propertyCount ≤ 63 | `CreateJSObjectWithProperties` → `GetObjectLiteralRootHClass` → `SetPropertyOfObjHClass`（`object_factory.cpp:5671-5707`、`4391-4439`） | 否：root HClass cache + `FindTransitions`（`js_hclass-inl.h:485-500`）命中即复用，未命中才 clone + transition |
| G11-B 大对象 | 63 < propertyCount ≤ 1023 | `CreateLargeJSObjectWithProperties` / `CreateLargeJSObjectWithNamedProperties`（`object_factory.cpp:5710-5747`、`5818-5849`） | 是：`CreateLayoutInfo(propertyCount)` 直分配，G11 主体 |
| G11-C 超限 | propertyCount > 1023 | `CreateDictionaryJSObjectWithProperties` / `...NamedProperties`（`object_factory.cpp:5749-5782`、`5852-5880`） | 否：创建 `NameDictionary`，无 fast LayoutInfo，排除 |


### 4.2 VM 内部执行

```cpp
// object_factory.cpp:5710-5747 — CreateLargeJSObjectWithProperties（G11-B）
// propertyCount 是本次运行时 API 调用传入的完整属性数（63 < N ≤ 1023）
JSHandle<LayoutInfo> layoutHandle = CreateLayoutInfo(propertyCount);
//             ↑ CreateLayoutInfo(N, SEMI, GROW)
//             → capacity = N + 4, 填入 N 个属性后 slack=4

for (size_t i = 0; i < propertyCount; ++i) {
    layout->AddKey(thread_, i, key, attr);
}
```

### 4.3 改为 KEEP 的性能分析

| 维度 | 现有 GROW (cap=N+4) | 改为 KEEP (cap=N) | 差异 |
|------|---------------------|-------------------|------|
| 构造时 N 次 AddKey | 原地写 | 原地写 | **零** |
| 修改已有属性值 | 不经过 LayoutInfo | 不经过 LayoutInfo | **零** |
| 追加新属性 | slack 内原地写 | **首次追加触发一次 Extend** | 一次分配+拷贝+屏障（操作级，未实测） |

**劣化场景可视化**（以 3 属性 N-API 对象构造完成后追加第 4 个属性为例）：

```text
GROW 现状：
  AddPropertyToNewHClass:
    cap=7 > 3 → 原地 AddKey → ExtraLength=4, slack=3 ✅

KEEP 改后：
  AddPropertyToNewHClass:
    cap=3 ≤ 3 → ExtendLayoutInfo!
      → 分配新数组 cap=3+4=7（与 GROW 初始分配完全相同！）
      → 拷贝 6 槽（3 属性 × 2 槽/属性）
      → AddKey → ExtraLength=4, slack=3
    从此行为与 GROW 完全一致
```

**时间线对比**（3 属性 N-API 对象构造完成后继续追加 4 个属性）：

```text
GROW 现状：
  创建 cap=7 → x,y,z,w,v,u,t 原地(第7属性填满) → 第8属性触发 Extend→cap=11
  总分配: 2次  总拷贝: 14槽

KEEP 改后：
  创建 cap=3 → x,y,z 原地 → w Extend→cap=7 → v,u,t 原地(第7属性填满) → 第8属性 Extend→cap=11
  总分配: 3次  总拷贝: 6+14=20槽
  额外代价: 1次分配 + 6槽拷贝（一次性，操作级模型，未实测）

  ← Extend 后 cap=7 与 GROW 初始分配完全相同，从此完全一致
  ← 不存在累加：只有第一次追加有差异
```

**风险约束**：N-API 路径的后续属性追加不受 ArkTS 编译器约束（N-API 是 native 侧调用）。需插桩确认 N-API 大对象构造后的追加概率。

### 4.4 V8 对照：native 侧批量属性构造

V8 没有"单次 native 调用传入 N 个属性名并预分配描述符数组"的等价路径：C++/N-API 侧创建对象（`v8::Object::New` / `napi_create_object`）从 native context 缓存的空对象 Map 起步，随后逐属性走普通 transition 链，描述符数组按条件性 slack 增长，超量 slack 可被 GC 右裁剪回收。

```cpp
// v8::Object::New → 初始 Map 为 context 缓存的空对象 Map（无属性、零 slack）
// 后续每个属性添加走：
//   Map::TransitionToDataProperty → Map::ShareDescriptor
//   容量不足时 EnsureDescriptorSlack(map, SlackForArraySize(old_size))：

if (descriptors->number_of_slack_descriptors() == 0) {
    int slack = Map::SlackForArraySize(old_size, kMaxNumberOfDescriptors);
    //   → old_size < 4: slack = 1（紧凑）
    //   → old_size ≥ 4: slack = old_size / 4（25% 增长）
    Map::EnsureDescriptorSlack(isolate, map, slack);
}
descriptors->Append(descriptor);  // 原地追加
```

**结构对比**：

| 维度 | V8 | ArkVM |
|------|-----|-------|
| 构造方式 | 空对象 Map 起步，逐属性 transition | 单次调用传入 N 个属性，预分配 cap=N+4 |
| 初始 capacity | 从 0 按需增长 | N + 4 |
| 稳态 waste | **零**（条件性 slack + GC 裁剪） | 最多 64 B（4 slack 属性位） |
| 后续追加 | `ShareDescriptor` + `SlackForArraySize`（条件性：小 +1、大 +25%） | `ExtendLayoutInfo` + 固定 +4 |
| GC 回收 | `TrimDescriptorArray` 物理右裁剪 | 无回收机制 |

**V8 的条件性增长公式**（`map-inl.h`）：

```cpp
int Map::SlackForArraySize(int old_size, int size_limit) {
    if (old_size < 4) return 1;                    // 小数组：+1
    return std::min(size_limit - old_size,
                    old_size / 4);                  // 大数组：+25%
}
```

对比 ArkVM 的 `ComputeGrowCapacity`：固定 `old_capacity + 4`，不随规模缩放。小对象（≤8 属性）的 GROW slack 恒为 4 个属性位（64 B），而 V8 同规模仅 +1 属性位（16 B）且可被 GC 回收。

---

## 5. 整体方案汇总

### 5.1 方案 A：三条路径 GROW→KEEP（源码候选）

将三条属性数可知的路径从 `GrowMode::GROW` 改为 `GrowMode::KEEP`。各路径的对象群体数量、后续追加概率和收益分摊需通过 creation-site 插桩归因确认，不能用快照全量 slack 按路径直接拆分：

| 子路径 | 源码位置 | 改动 | 属性数来源   | 劣化 | 风险 |
|------|---------|------|----------|------|------|
| **A1-A：bootstrap 函数类** | `object_factory.cpp:2029-2075` | `GROW` → `KEEP` | FunctionKind 分支决定 2-3 属性（§2.3 表） | 发布后若有追加则首次 Extend | 需插桩确认追加闭包 |
| **A1-B：N-API 类函数** | `object_factory.cpp:5902/5909` + helper 事务 | `GROW` → `KEEP` | max_write = 3 + inlinedStaticPropCount |—（无 transition 追加即越界） | 无 Extend fallback，容量须按事务最大无 transition offset |
| **A1-C：N-API 类 prototype** | `object_factory.cpp:5887` + helper 事务 | `GROW` → `KEEP` | max_write = 1 + inlNonStaticPropCount | —（同上） | 同上，与 A1-B 独立建表 |
| **A2：字典迁移（named-property）** | `js_hclass.cpp:719-746`（仅 isDictionary=true 分支；G10-E elements 另行统计） | `GROW` → `KEEP` | `EntriesCount()` 已知 | 迁移后追加触发一次 Extend | 迁移本身意味着形状已稳定，追加概率低 |
| **A3：N-API 大对象（G11-B）** | `object_factory.cpp:5722,5829`（63<N≤1023） | `GROW` → `KEEP` | `propertyCount` 由 API 参数运行时传入 |  构造后追加触发一次 Extend | N-API 追加不受编译器约束，需插桩 |
| **合计** | | | | （快照全量上界约束：快手前台 3.19 MiB、TOP13 合计 19.71 MiB） | | |

改动均为参数级别变更，不修改任何逻辑代码；但子路径不能合并为统一 KEEP 参数，须逐子路径建立容量账本：


### 5.2 方案 B：调整 GROW 增长公式

对**保留 GROW 模式**的路径（动态属性场景），将固定 +4 改为条件性增长：

```cpp
// layout_info.h — 现有实现
static inline uint32_t ComputeGrowCapacity(uint32_t old_capacity) {
    uint32_t new_capacity = old_capacity + MIN_PROPERTIES_LENGTH;  // 固定 +4
    return new_capacity > MAX_PROPERTIES_LENGTH ? MAX_PROPERTIES_LENGTH : new_capacity;
}

// 修改后：小 Layout 紧凑增长，大 Layout 保持 +4
static inline uint32_t ComputeGrowCapacity(uint32_t old_capacity) {
    uint32_t slack;
    if (old_capacity < 16) {
        slack = std::max(old_capacity / 4, 1U);  // 25% 取整，最小预留 1
    } else {
        slack = MIN_PROPERTIES_LENGTH;             // ≥16 属性固定 +4
    }
    uint32_t new_capacity = old_capacity + slack;
    return new_capacity > MAX_PROPERTIES_LENGTH ? MAX_PROPERTIES_LENGTH : new_capacity;
}
```

**增长效果对比**：

| 需要属性数 | 现有 capacity (+4) | 新 capacity (条件性) | 节省槽位 | 节省字节 |
|----------:|------------------:|-------------------:|--------:|--------:|
| 1 | 5 | 2 | 3 | 48 B |
| 2 | 6 | 3 | 3 | 48 B |
| 3 | 7 | 4 | 3 | 48 B |
| 4 | 8 | 5 | 3 | 48 B |
| 5 | 9 | 7 | 2 | 32 B |
| 8 | 12 | 10 | 2 | 32 B |
| 12 | 16 | 15 | 1 | 16 B |
| 16 | 20 | 20 | 0 | 0 |
| 20 | 24 | 24 | 0 | 0 |

**交叉点**：属性数 <16 时新策略更紧凑（≤8 属性节省 32-48 B），≥16 时与现有 +4 等价。

**扩容频率变化**：

| 属性范围 | 现有增长步长 | 新增长步长 | 扩容频率变化 |
|---------|-----------|---------|-----------|
| 1-4 | +4 | +1 | 更频繁（每属性一次 Extend） |
| 5-8 | +4 | +1~2 | 更频繁 |
| 9-15 | +4 | +2~3 | 略频繁 |
| ≥16 | +4 | +4 | **不变** |

小 Layout 的扩容频率增高的代价：每次 Extend 是一次分配+拷贝+屏障操作（操作级模型，未实测）。对于一次性创建后不再追加的 ArkTS 对象（96% 属性 ≤9），实际触发的 Extend 次数极少。

### 5.3 方案 A+B 组合效果（结构性上界）

以下收益来自快照结构性 slack 上界，不能直接拆分归因到各路径。需完成 creation-site 插桩归因后确定各路径独立贡献。快照全量结构性 slack 上界：快手前台 3.19 MiB、后台 2.96 MiB、TOP13 合计 19.71 MiB。

| 方案 | 覆盖范围 | 收益 | 性能影响 | 建议 |
|------|---------|------|---------|------|
| A：三路径 KEEP | 函数类 HClass + 字典迁移 + N-API 大对象 | 需 creation-site 归因（含于全量上界内） | 创建期均原地写；发布后首次追加各触发一次 Extend | 源码候选 |
| B：GROW 公式调整 | 其余所有 GROW 路径 | 模型估算 ~0.8-1.5 MiB（快手前台，需按属性分布复核） | 小 Layout 扩容频率略增 | 在部分路径实施 |
| **A+B 合计** | 全部 LayoutInfo 分配 | 以快照全量结构性 slack 上界为约束（快手前台 3.19 MiB、后台 2.96 MiB、TOP13 合计 19.71 MiB） | | |


### 5.4 性能表现汇总

#### 创建路径性能

| 操作 | 现有 | 方案 A 后 | 方案 B 后 | 差异来源 |
|------|------|----------|----------|---------|
| 函数类 HClass 创建 | cap=7, ≤3 次 AddKey | cap=3, ≤3 次 AddKey | 不变 | **零差异**（均原地写） |
| 字典→fast 迁移 | cap=N+4, N 次 AddKey | cap=N, N 次 AddKey | 不变 | **零差异**（均原地写） |
| N-API 大对象构造 | cap=N+4, N 次 AddKey | cap=N, N 次 AddKey | 不变 | **零差异**（均原地写） |
| 动态对象属性追加 | cap=N+4, slack 内原地写 | 追加时首次触发一次 Extend | cap=N+25%, 可能触发 Extend | 首次各多一次 Extend（B 策略） |

#### 属性访问性能（热路径）

| 操作 | 现有 | 方案 A 后 | 方案 B 后 | 差异 |
|------|------|----------|----------|------|
| 属性查找（IC 命中） | O(1) 固定偏移 | 不变 | 不变 | **零**（不经 LayoutInfo 容量） |
| 属性查找（IC miss → LookupProperty） | O(N) LayoutInfo 线性/二分 | 不变 | 不变 | **零**（不依赖 capacity） |
| for-in 枚举 | 读 LayoutInfo keys | 不变 | 不变 | **零** |
| GC 标记扫描 | 扫描 Length 槽 | 扫描更少（cap 更小） | 扫描更少 | **正向**（扫描量下降） |

#### 扩容（ExtendLayoutInfo）性能

| 场景 | 现有频率 | 方案 B 后频率 | 每次成本 | 总影响 |
|------|---------|------------|---------|--------|
| ArkTS 类对象（属性固定） | ~0（一次性创建） | ~0（同） | — | **零** |
| 动态对象（属性 ≤8） | 每 4 属性一次 | 每 1-2 属性一次 | 一次分配+拷贝+屏障（未实测） | 每属性最多多一次 Extend（一次性） |
| 大对象（属性 ≥16） | 每 4 属性一次 | 每 4 属性一次 | 一次分配+拷贝+屏障（未实测） | **不变** |

#### GC 影响

| 维度 | 现有 | A+B 后 | 方向 |
|------|------|--------|------|
| 标记量 | 扫描全部 Length 槽 | LayoutInfo 更小 → 扫描槽减少 | ✅ 正向 |
| 分配压力 | 每次 GROW 分配 N+4 槽 | 分配 N 或 N+25% 槽 → 更小对象 | ✅ 正向 |
| 暂停时间 | — | 无新增暂停点 | 零变化 |
| 碎片 | — | 更小对象可能改善碎片 | 略正向 |

#### 性能门槛（放行前置条件）

| 指标 | 放行线 |
|------|-------|
| 属性查找/枚举 | 零回退 |
| GC pause | ≤ 1% 回退 |
| 扩容率（Extend/create 比值） | 监控，不设硬门槛 |
| 快手前台 LayoutInfo shallow | 下降 ≥ 2.0 MiB |

### 5.5 结论

1. **方案 A 是源码候选，粒度为子路径**——G1-A/G1-B/G1-C、G10（named-property）、G11-B 的属性上界已按源码核验，但对象群体数量、追加概率和各子路径收益分摊需 creation-site 插桩归因，三条路径不能合并为统一的 KEEP 参数改动；
2. **方案 B（GROW 公式调整）是待全量验证实验**——需逐调用点验证写入闭包，不与方案 A 叠加收益；
3. **A+B 合计受快照全量结构性 slack 上界约束**（快手前台 3.19 MiB、后台 2.96 MiB、TOP13 合计 19.71 MiB）——需 creation-site 归因后确定各路径独立贡献；
4. **热路径零影响**——属性查找、IC、枚举完全不经过 LayoutInfo 容量机制；
5. **GC 正向**——LayoutInfo 对象更小、标记扫描量下降、分配压力减少；
