# 三大 GROW→KEEP 转换路径：逐路径浪费分析与 V8 对照

本文档对 LayoutInfo 当前使用 `GrowMode::GROW`（固定 +4 slack）的三条最大浪费路径进行源码级分析，包含代码示例、浪费可视化、性能定量和 V8 对照。

## 目录

1. [全部 LayoutInfo 分配路径总览](#1-全部-layoutinfo-分配路径总览)
2. [路径 G1：函数 HClass LayoutInfo](#2-路径-g1函数-hclass-layoutinfo)
3. [路径 G10：字典→fast 迁移](#3-路径-g10字典fast-迁移)
4. [路径 G11：对象字面量属性填充](#4-路径-g11对象字面量属性填充)
5. [汇总与结论](#5-汇总与结论)

---

## 1. 全部 LayoutInfo 分配路径总览

### 1.1 KEEP 精确分配（11 个路径，零浪费）

| # | 调用点 | 创建什么 | 属性来源 |
|---|--------|---------|---------|
| K1 | `class_info_extractor.cpp:216` | 类 prototype LayoutInfo | abc 静态元数据 |
| K2 | `class_info_extractor.cpp:266` | 类 static LayoutInfo | abc 静态元数据 |
| K3 | `js_hclass.cpp:1495` | 对象字面量 root HClass | 编译期字面量属性列表 |
| K4 | `js_hclass.cpp:1526` | 对象字面量（另一路径） | 编译期 |
| K5 | `object_factory.cpp:2085` | 默认类 prototype HClass | 固定 schema |
| K6 | `object_factory.cpp:2105` | 默认类 prototype 变体 | 固定 schema |
| K7 | `global_env_constants.cpp:577` | 空 LayoutInfo（常量） | 0 属性 |

### 1.2 GROW +4 slack（12 个路径，每 LayoutInfo 浪费 64 B）

| # | 调用点 | 创建什么 | 典型属性数 | 浪费/Layout | 快照占比 |
|---|--------|---------|----------|-----------|---------|
| **G1** | `object_factory.cpp:2034-2036` | **函数 HClass LayoutInfo** | 1-2 | **64 B** | **~30%** |
| G2 | `builtins.cpp:428` | 内建函数 LayoutInfo | 1-2 | 48-64 B | <1% |
| G3 | `builtins.cpp:553` | Function.prototype 属性 | 2-3 | 48-64 B | <1% |
| G4 | `builtins.cpp:586` | Function 静态属性 | 1-3 | 32-64 B | <1% |
| G5 | `js_array.cpp:970` | Array 函数类 LayoutInfo | 1 | 64 B | <1% |
| G6 | `js_array.cpp:1007` | Array prototype LayoutInfo | 1 | 64 B | <1% |
| G7 | `object_factory.cpp:882` | RegExp 类 LayoutInfo | 1 | 64 B | <1% |
| G8 | `object_factory.cpp:907` | Array length 属性 | 1 | 64 B | <1% |
| G9 | `object_factory.cpp:935` | Arguments length 属性 | 1 | 64 B | <1% |
| **G10** | `js_hclass.cpp:731` | **字典→fast 迁移** | N | **64 B** | **~10%** |
| **G11** | `object_factory.cpp:5722,5829` | **对象字面量属性填充** | N | **64 B** | **~15%** |
| G12 | `object_factory.cpp:5423,4340` | Iterator/其他 | 2-N | 32-64 B | ~2% |

---

## 2. 路径 G1：函数 HClass LayoutInfo

### 2.1 应用代码

```ts
// 每个模块的每个函数声明/表达式
export function add(a: number, b: number): number { return a + b; }
export const multiply = (x: number) => x * 2;
export class Calculator { /* ... */ }
```

### 2.2 VM 内部执行

```cpp
// object_factory.cpp:2031-2056
uint32_t fieldOrder = 0;

// 创建 LayoutInfo，GrowMode 默认 GROW
layoutInfoHandle = CreateLayoutInfo(JSFunction::LENGTH_OF_INLINE_PROPERTIES);
//             ↑ CreateLayoutInfo(2, SEMI_SPACE, GrowMode::GROW)
//             → ComputeGrowCapacity(2) = 2 + 4 = 6
//             → 分配 capacity=6 的数组，self_size = 16 + 16×6 = 112 B

// 立即填入 length（第 1 个属性）
layoutInfoHandle->AddKey(thread_, 0, "length", attributes);
// → ExtraLength: 0→1, capacity=6, slack=5

// 立即填入 name（第 2 个属性，class constructor 除外）
layoutInfoHandle->AddKey(thread_, 1, "name", attributes);
// → ExtraLength: 1→2, capacity=6, slack=4

// ← 此后再无属性追加！length 和 name 是函数仅有的两个属性
// 4 个 slack 槽（64 B）从此永久闲置
```

### 2.3 浪费可视化

```text
┌───────────────────────────────────────────────┐
│ LayoutInfo (capacity=6, self_size=112 B)     │
├───────────────────────────────────────────────┤
│ slot[0]  key="length"  attr=... │ ← 有效     │
│ slot[1]  attr                │ ← 有效        │
│ slot[2]  key="name"    attr=... │ ← 有效     │
│ slot[3]  attr                │ ← 有效        │
│ slot[4]  Hole                │ ← ★ 浪费 16 B │
│ slot[5]  默认attr             │ ← ★ 浪费 16 B │
│ slot[6]  Hole                │ ← ★ 浪费 16 B │
│ slot[7]  默认attr             │ ← ★ 浪费 16 B │
│ slot[8]  Hole                │ ← ★ 浪费 16 B │
│ slot[9]  默认attr             │ ← ★ 浪费 16 B │
│ slot[10] Hole                │ ← ★ 浪费 16 B │
│ slot[11] 默认attr             │ ← ★ 浪费 16 B │
└───────────────────────────────────────────────┘

浪费 = 4 个属性位 × 16 B = 64 B / LayoutInfo
KEEP 版本只需 16+16×2 = 48 B，节省 64 B（57%）
```

### 2.4 改为 KEEP 的性能分析

```cpp
// 修改后（1 行）
layoutInfoHandle = CreateLayoutInfo(JSFunction::LENGTH_OF_INLINE_PROPERTIES,
                                     MemSpaceType::SEMI_SPACE, GrowMode::KEEP);
// capacity = 2, self_size = 48 B
// AddKey #1 (length) → ExtraLength=1, cap=2 ✅
// AddKey #2 (name)   → ExtraLength=2, cap=2 ✅ 刚好满
```

| 维度 | 现有 GROW | 改为 KEEP | 差异 |
|------|----------|----------|------|
| 分配大小 | 112 B | 48 B | **-64 B** |
| AddKey 次数 | 2 次（原地） | 2 次（原地） | **零** |
| Extend 触发 | 从不 | 从不 | **零** |
| 后续追加 | 从不（函数属性固定） | 从不 | **零** |

**性能劣化：零。不存在累加**——函数的 `length` 和 `name` 属性集是封闭的，在创建时一次性全部填入，此后不会再有任何属性追加到该 LayoutInfo。

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
| waste | **零**（共享 + 无 slack） | 64 B × 每个函数 |

**ArkVM 差异的根源**：ArkVM 为每个函数 HClass 独立调用 `CreateLayoutInfo(2, GROW)`，而非从 GlobalEnv 缓存复用。V8 的做法等价于将此路径的 `GrowMode` 从 `GROW` 改为 `KEEP` 并加上 context 级共享——即使不做共享，仅改 `KEEP` 即可消除 64 B/函数的浪费。

---

## 3. 路径 G10：字典→fast 迁移

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

### 3.2 VM 内部执行

```cpp
// js_hclass.cpp:725-750 — 迁移时创建新 LayoutInfo
int numberOfProperties = properties->EntriesCount();  // ← 属性数已知！
JSHandle<LayoutInfo> layoutInfoHandle = factory->CreateLayoutInfo(numberOfProperties);
//             ↑ CreateLayoutInfo(N, SEMI, GROW)
//             → capacity = N + 4

// 然后逐个填入 N 个属性
for (int i = 0; i < numberOfProperties; i++) {
    JSTaggedValue key = properties->GetKey(thread, indexOrder[i]);
    layoutInfoHandle->AddKey(thread_, i, key, attributes);
}
// 填完后 ExtraLength=N, capacity=N+4, slack=4 → 浪费 64 B
```

### 3.3 改为 KEEP 的性能分析

| 维度 | 现有 GROW | 改为 KEEP | 差异 |
|------|----------|----------|------|
| 迁移时的 N 次 AddKey | 原地写（cap=N+4） | 原地写（cap=N） | **零** |
| 迁移后追加属性 | 用 slack 原地写（~10 ns） | **触发一次 Extend（~110 ns）** | **+100 ns** |

**劣化场景**（迁移后追加属性）：

```text
GROW 现状：
  cap=N+4 > N → 原地 AddKey (~10ns)

KEEP 改后：
  cap=N ≤ N → ExtendLayoutInfo
    → 分配新数组 cap=N+4（与 GROW 初始分配相同！）
    → 拷贝 2N 槽（N 属性 × 2 槽/属性）
    → AddKey
    代价 = 1 次分配 (~50ns) + 2N 槽拷贝 (~20ns) + 写屏障 (~40ns) ≈ ~110ns
```

**累加？不会**——Extend 后新数组获得 +4 slack（capacity=N+4），与 GROW 初始分配完全相同，后续行为立即收敛。整个生命周期只多一次 Extend。

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

## 4. 路径 G11：对象字面量属性填充

### 4.1 应用代码

```ts
// 应用代码
const point = { x: 1, y: 2, z: 3 };  // 3 个属性的对象字面量
```

### 4.2 VM 内部执行

```cpp
// object_factory.cpp:5720-5740 — 字面量路径
JSHandle<LayoutInfo> layoutHandle = CreateLayoutInfo(propertyCount);
//             ↑ CreateLayoutInfo(3, SEMI, GROW)
//             → capacity = 3 + 4 = 7, self_size = 16 + 16×7 = 128 B

// 逐个填入 3 个属性
for (size_t i = 0; i < propertyCount; ++i) {
    layout->AddKey(thread_, i, key, attr);
}
// 填完后 ExtraLength=3, capacity=7, slack=4 → 浪费 64 B
```

### 4.3 改为 KEEP 的性能分析

| 维度 | 现有 GROW (cap=7) | 改为 KEEP (cap=3) | 差异 |
|------|-------------------|-------------------|------|
| 字面量创建时 3 次 AddKey | 原地写 (~30ns) | 原地写 (~30ns) | **零** |
| `point.x = 10`（改已有属性） | 不经过 LayoutInfo | 不经过 LayoutInfo | **零** |
| `point.w = 4`（追加新属性） | 原地写 cap=7>3 (~10ns) | **触发 Extend (~110ns)** | **+100ns** |

**劣化场景可视化**（追加第 4 个属性 `point.w = 4`）：

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

**时间线对比**（对象 `{x,y,z}` 后续加 w, v, u, t）：

```text
GROW 现状：
  创建 cap=7 → x,y,z 原地 → w 原地 → v 原地 → u 原地 → t 原地(cap满) → Extend→cap=11
  总分配: 2次  总拷贝: 14槽

KEEP 改后：
  创建 cap=3 → x,y,z 原地 → w Extend→cap=7(~110ns) → v 原地 → u 原地 → t 原地(cap满) → Extend→cap=11
  总分配: 3次  总拷贝: 6+14=20槽
  额外代价: 1次分配 + 6槽拷贝 ≈ ~80ns（一次性）

  ← Extend 后 cap=7 与 GROW 初始分配完全相同，从此完全一致
  ← 不存在累加：只有第一次追加有差异
```

**累加？不会**——Extend 后的 capacity 与 GROW 初始分配完全相同，后续走同一条演化路径。整个生命周期只多一次 Extend。

**严格 ArkTS 风险为零**：对象字面量 `{x:1, y:2, z:3}` 的后续追加 `obj.w = 4` 在编译期即被禁止（`w` 未声明）。

### 4.4 V8 对照：对象字面量

V8 的对象字面量通过 `Factory::ObjectLiteralMapFromCache`（`src/heap/factory.cc`）从 native context 缓存获取初始 Map，属性数精确匹配。

**V8 的对象字面量 Map 获取流程**：

```cpp
// factory.cc — ObjectLiteralMapFromCache
Handle<Map> Factory::ObjectLiteralMapFromCache(
    Handle<NativeContext> context, int number_of_properties) {
    
    // 从 native_context 的 object_literal_map_cache 取缓存
    // cache 按 number_of_properties 索引，kMapCacheSize = 128
    Handle<FixedArray> cache(context->object_literal_map_cache());
    
    if (number_of_properties < kMapCacheSize) {
        Handle<Object> maybe_map(cache->get(number_of_properties));
        if (maybe_map->IsMap()) {
            return Handle<Map>::cast(maybe_map);  // ← 缓存命中，直接复用
        }
    }
    
    // 缓存未命中 → 创建新 Map（初始 Map，无属性）
    Handle<Map> map = NewMap(JS_OBJECT_TYPE, JSObject::kHeaderSize);
    
    // 后续通过 transition 链逐属性添加
    // 走 ShareDescriptor + SlackForArraySize（条件性 slack）
    if (number_of_properties < kMapCacheSize) {
        cache->set(number_of_properties, *map);  // 存入缓存供后续复用
    }
    return map;
}
```

**V8 字面量创建后的属性追加**：

```cpp
// 对象字面量的属性通过 boilerplate + clone 或逐属性 transition 填充
// 追加新属性时走 Map::ShareDescriptor：

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
| 初始 Map 来源 | `ObjectLiteralMapFromCache` per-context 缓存（按属性数索引） | `CreateLayoutInfo(propertyCount, GROW)` 每次新分配 |
| 初始 capacity | 属性数精确匹配（缓存命中时零分配） | propertyCount + 4 |
| 初始 waste | **零**（缓存 + 精确） | 64 B |
| 后续追加 | `ShareDescriptor` + `SlackForArraySize`（条件性：小 +1、大 +25%） | `ExtendLayoutInfo` + 固定 +4 |
| GC 回收 | `TrimDescriptorArray` 物理右裁剪 | 无回收机制 |

**V8 的条件性增长公式**（`map-inl.h:1267`）：

```cpp
int Map::SlackForArraySize(int old_size, int size_limit) {
    if (old_size < 4) return 1;                    // 小数组：+1
    return std::min(size_limit - old_size,
                    old_size / 4);                  // 大数组：+25%
}
```

对比 ArkVM 的 `ComputeGrowCapacity`：固定 `old_capacity + 4`，不随规模缩放。小数组（≤8 属性）的浪费恒定为 64 B，而 V8 仅为 16 B（+1 属性位）且可被 GC 回收。

---

## 5. 汇总与结论

| 路径 | 浪费量级 | 改 KEEP 后劣化 | 累加 | 风险 | V8 行为 | 改动量 |
|------|---------|---------------|------|------|---------|-------|
| G1 函数 HClass | 64 B × ~20,000 ≈ **1.2 MiB** | **零** | 不会 | **零** | per-context 共享 | 1 行 |
| G10 字典迁移 | 64 B × ~7,000 ≈ **0.4 MiB** | 一次性 ~110 ns | 不会 | 极低 | slack=0，已精确 | 1 行 |
| G11 对象字面量 | 64 B × ~10,000 ≈ **0.6 MiB** | 一次性 ~110 ns | 不会 | 低（严格 ArkTS 为零） | 缓存精确初始 Map | 1-2 行 |
| **合计** | **~2.2 MiB** | | | | | **3-4 行** |

### 关键结论

1. **G1（函数 HClass）是零风险零代价的纯收益**——函数的 length/name 属性集是封闭的，不存在后续追加场景；
2. **G10 和 G11 的劣化都是一次性的**（首次追加多付 ~100 ns），不会累加——Extend 后的 capacity 与 GROW 初始分配完全相同，从此走同一条路径；
3. **严格 ArkTS 下 G11 的风险实际为零**——对象字面量的后续追加在编译期就被禁止；
4. 三条路径的改动均为 1-2 行参数变更，不需要修改任何逻辑代码。
