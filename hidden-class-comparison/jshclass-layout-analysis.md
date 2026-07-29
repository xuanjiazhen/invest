# ArkVM JSHClass 对象布局分析报告

> 来源: OpenHarmony `js_hclass.h:2214-2226`, V8 `src/objects/map.h (public)`, JSC `runtime/Structure.h`, Hermes `include/hermes/VM/HiddenClass.h`
> 字段大小均从 ACCESSORS 宏偏移量精确计算。

---

## 第一部分: JSHClass 布局全景

### 1.1 整体结构 (120B 含 inlined props)

```
偏移   大小   字段                      产生方               消费方
──────────────────────────────────────────────────────────────────────────
 0      8 B   TaggedObjectHeader         VM 堆分配器          GC / 类型判断
 8      4 B   BitField (uint32)          Init 阶段设置         IsCallable/IsConstructor 等快速判断
12      4 B   BitField1 (uint32)         HClass 初始化时       ObjectSize / InlinedPropsStart
16      8 B   Proto                      Clone/NewEcmaHClass  属性查找链、原型链遍历
24      8 B   Layout                     CreateLayoutInfo     属性枚举 for-in / JSON.stringify / JIT 优化
32      8 B   Transitions                AddProperty 时       属性添加 → 查找已有 shape
40      8 B   Parent                     Clone 时设置         反向遍历、GC tracing
48      8 B   ProtoChangeMarker          MarkProtoChanged     for-in 缓存失效判断
56      8 B   ProtoChangeDetails         同上                 同上
64      8 B   EnumCache                  GetOrCreateEnumCache for-in / JSON.stringify 快速键枚举
72      8 B   DependentInfos             JIT 优化代码绑定     优化代码失效通知
80      8 B   BitField2 (uint64)         Init / Transition    ASAN check / 类型判断
── 88 B (DEFINE_ALIGN_SIZE)
+ 4 × 8B inlined slots (DEFAULT_CAPACITY_OF_IN_OBJECTS = 4)
── 120 B
```

### 1.2 逐字段详解

#### TaggedObjectHeader (0-8B)

- **产生**: `Heap::AllocateYoungOrHugeObject` 调用时由 VM 分配器写入
- **消费**: GC 遍历对象图、`JSTaggedValue::IsJSHClass()` 类型判断
- **竞品对比**: V8 在 pointer-compression 下 Header 仅 4B (compressed map pointer); JSC 通过 IsoSubspace 分配无需显式 header

#### BitField (8-12B, uint32_t)

- **产生**: `JSHClass::Initialize` 过程中根据 `JSType` 设置
- **内容**: `JSType` (8 bits) + `IsCallable` (1) + `IsConstructor` (1) + `IsExtensible` (1) + `IsPrototype` (1) + `ElementsKind` (5) + `IsDictionaryElement` (1) + `IsDictionary` (1) + ...
- **消费**: 极高频——每次属性访问的 IC (Inline Cache) 都需检查 `IsDictionary`
- **竞品**: V8 用 `instance_type` (2B u16) + 三个独立的 `bit_field` (1B+1B+4B); JSC 用 `m_outOfLineTypeFlags` (4B)

#### BitField1 (12-16B, uint32_t)

- **产生**: `JSHClass::Initialize` 时计算
- **内容**: `NumberOfProps` (10 bits: 最多 1023) + `InlinedPropsStart` (5 bits) + `ObjectSizeInWords` (15 bits)
- **消费**: 属性偏移计算 `GetInlinedPropertyOffset(index)`
- **竞品**: V8 用 `instance_size_in_words` (1B u8) + `inobject_properties` (1B u8)

#### Proto (16-24B)

- **产生**: `CreateFunctionClass` / `Clone` 时从原型链复制或设置
- **消费**: 属性查找链 (prototype chain walk)
- **竞品**: V8 同样有 `prototype` 字段 (4B compressed ptr)

#### Layout (24-32B)

- **产生**: `CreateLayoutInfo(inlinedProps)` → 每个 inlined property 记录 name + attr
- **内容**: `LayoutInfo` = TaggedArray，每个 entry 是属性名+属性标志的 packed tuple
- **消费**: for-in 枚举键列表、`JSHClass::GetAllEnumKeys`、Baseline JIT stub
- **竞品**: V8 `instance_descriptors` (DescriptorArray) — 功能相同但共享机制更优

#### Transitions (32-40B)

- **产生**: 每次 `AddProperty` → `AddPropertyToNewHClass` → 插入 transition 链表头
- **消费**: 后续属性添加时查找 → 遍历 `Transitions` 链表 O(n)
- **瓶颈**: 每个 HClass 分配时 **完整 Clone (120B)**，然后只修改 transition
- **竞品**: V8 `TransitionArray` — 树形 (hash-based)，O(1) 查找，共享 DescriptorArray

#### Parent (40-48B)

- **产生**: `Clone` 时 `newHClass->SetParent(oldHClass)`
- **消费**: GC tracing 中反向引用
- **竞品**: JSC `m_previous` (等同); V8 不存储 parent (反向指针隐含在 transition 树中)

#### ProtoChangeMarker (48-56B) + ProtoChangeDetails (56-64B)

- **产生**: `MarkProtoChanged` → 原型被修改时设置标记
- **消费**: for-in 枚举时检查 `IsEnumCacheValid` → 若原型变更, EnumCache 失效
- **冗余分析**: V8 用 `prototype_validity_cell` (已在 Map 内) + 1 bit 标志位完成同样的工作。ArkVM 额外用了 **16B** 存储两个独立对象。
- **优化空间**: 合并 ProtoChangeMarker 的单 bool 标志到 BitField2，ProtoChangeDetails 移到 side table。

#### EnumCache (64-72B)

- **产生**: `GetOrCreateEnumCacheFromHClass` → for-in 首次调用时创建 (已是惰性)
- **消费**: for-in / JSON.stringify / JIT stub 中 `GetEnumCacheOwn`
- **实际情况**: 内容已惰性，**字段槽始终占用 8B**。`Initialize` 时设为 `Null()`
- **优化空间**: 移到 side table → 8B 节省，但需改 Baseline JIT stub

#### DependentInfos (72-80B)

- **产生**: JIT 编译器将优化代码绑定到特定 HClass 时
- **消费**: HClass 变更时通知所有依赖代码失效 (deoptimization)
- **竞品**: V8 `dependent_code` — 功能相同，但使用 WeakArrayList 实现
- **优化空间**: 移到 side table — 仅 HClass 被 JIT 优化时才需要

#### BitField2 (80-88B, uint64_t)

- **产生**: `Initialize` + transition 过程中按需设置额外标志
- **消费**: ASAN check、类型安全检查
- **竞品**: V8 `bit_field3` (4B u32) — 功能等价但更紧凑

### 1.3 大小占比

```
TaggedObjectHeader   8B ████████
BitField             4B ████
BitField1            4B ████
Proto                8B ████████
Layout               8B ████████
Transitions          8B ████████
Parent               8B ████████
ProtoChangeMarker    8B ████████  ← 可优化
ProtoChangeDetails   8B ████████  ← 可优化
EnumCache            8B ████████  ← 可优化
DependentInfos       8B ████████  ← 可优化
BitField2            8B ████████
inlined×4            32B ████████████████████████████████
─────────────────────────────────
合计                 120B
可优化部分           32B (27%)
```

---

## 第二部分: 竞品逐字段对比

### 2.1 V8 Map

| V8 字段 | 对应 ArkVM 字段 | V8 大小 | ArkVM 大小 | V8 优势 |
|---------|----------------|---------|-----------|---------|
| instance_type | BitField | 2B | 4B | 更紧凑的类型编码 |
| instance_size + inobject | BitField1 | 2B | 4B | u8 足够表示大小 |
| bit_field + bf2 + bf3 | BitField2 | 5B | 8B | 分散存储，部分可压缩 |
| prototype_validity_cell | ProtoChangeMarker+Details | **0B (内嵌)** | **16B** | V8 用单 cell 完成 |
| dependent_code | DependentInfos | 4B | 8B | WeakArrayList, 外置 |
| transitions | Transitions | 4B | 8B | TransitionArray (树) |
| instance_descriptors | Layout | 4B | 8B | DescriptorArray 共享 |
| **所有指针** | **所有指针** | **4B (compressed)** | **8B** | **−36B 纯指针差** |

### 2.2 JSC Structure

| 维度 | JSC | ArkVM | 差异 |
|------|-----|-------|------|
| 总大小 | ~64B | ~120B | JSC 压缩 45% |
| 指针数量 | 5 ptrs | 9 ptrs | 无 ProtoChangeMarker/Details/EnumCache/DependentInfos |
| Transition | single-item + PropertyTable | 链表 | JSC 用 PropertyTable 共享属性存储 |
| 分配策略 | IsoSubspace (size-class) | SemiSpace bump ptr | JSC 分配更快 |
| 原型有效性 | 1 bit in Structure | 16B (2 ptrs) | JSC 极简 |

### 2.3 Hermes HiddenClass

| 维度 | Hermes | ArkVM | 差异 |
|------|--------|-------|------|
| 总大小 | ~32-48B | ~120B | Hermes 极致压缩 |
| Transition | 无 transition 链 | 链表 | Hermes 在 property map 中查找 |
| Proto 相关 | 无 | 16B | Hermes 不维护原型变更追踪 |
| EnumCache | 无 | 8B | Hermes for-in 直接遍历 |
| 适用场景 | 移动端低内存 | 通用 | ArkVM 支持更多 JIT 优化 |

---

## 第三部分: 优化方案矩阵

### 方案 A: ProtoChange 字段合并 (−16B)

| 项目 | 内容 |
|------|------|
| **预估效果** | 每个 JSHClass 节省 16B (13%) |
| **改动范围** | `js_hclass.h` (移除 2 字段), `js_hclass.cpp` (访问路径改为 BitField2 flag + side table) |
| **兼容性** | ✅ 不涉及 JIT stub 修改；AOT 路径 `MarkProtoChanged` 改为函数调用 |
| **稳定性** | 低风险。ProtoChange 仅原型修改时触发，频率极低 |

具体: `ProtoChangeMarker` → BitField2 占用 1 bit。`ProtoChangeDetails` → 全局 Hash map (仅在原型变化时写入)。

### 方案 B: DependentInfos 外移 (−8B)

| 项目 | 内容 |
|------|------|
| **预估效果** | 每个 JSHClass 节省 8B |
| **改动范围** | `js_hclass.h`, `js_hclass.cpp`, JIT deoptimization 路径 |
| **兼容性** | ⚠️ JIT 的 deopt 通知需要从直接读取改为 side table 查找 |
| **稳定性** | 中风险。依赖代码失效通知是 JIT 稳定性的关键路径 |

### 方案 C: EnumCache Side Table (−8B)

| 项目 | 内容 |
|------|------|
| **预估效果** | 每个 JSHClass 节省 8B |
| **改动范围** | JSHClass + Baseline JIT stub + Interpreter |
| **兼容性** | ⚠️ Baseline JIT stub 需改为 runtime call |
| **稳定性** | 中风险。Baseline JIT 是高频路径 |

### 方案 D: Transition 树替代链表 (性能优化)

| 项目 | 内容 |
|------|------|
| **预估效果** | Transition 查找 O(n)→O(1); DescriptorArray 共享减少 Layout 重复 |
| **改动范围** | 全新数据结构 `TransitionArray` + `Clone` 逻辑重写 + GC 适配 |
| **兼容性** | ⚠️⚠️ 核心数据结构变更 |
| **工作量** | 大 (估计 2-3 人月) |

### 方案 E: Pointer Compression (长线)

| 项目 | 内容 |
|------|------|
| **预估效果** | 每个 JSHClass 节省 36B (9 ptrs × 4B) + 全 VM 受益 |
| **改动范围** | 全 VM (GC、interpreter、JIT、stubs) |
| **兼容性** | ⚠️⚠️⚠️ 需类似 V8 2019 年的全 VM 改造 |
| **工作量** | 极大 (团队级项目) |

### 方案 F: JSApiFunction 裁剪 (已实现)

| 项目 | 内容 |
|------|------|
| **预估效果** | API 函数对象从 ~112B → ~80B (每个 −32B) |
| **当前状态** | ✅ 已在 `ENABLE_API_FUNCTION_OPTIMIZATION` + `ENABLE_MEMORY_OPTIMIZATION` 路径下实现 |
| **覆盖范围** | 所有 N-API 函数 (`New`, `NewConcurrent`, `NewClassFunction`) |

### 推荐实施顺序

```
第1批 (低风险, 立即做):
  ├─ 方案 A: ProtoChange 合并    −16B  低风险
  └─ 方案 B: DependentInfos 外移  −8B  中低风险
  
第2批 (中等风险):
  └─ 方案 C: EnumCache side table  −8B  中等风险

第3批 (长期):
  ├─ 方案 D: Transition 树        0B   架构优化
  └─ 方案 E: Pointer Compression  −36B  全 VM 改造

第1批完成后: JSHClass 120B → 96B (与 V8 的差距 2.2× → 1.8×)
全部完成后: JSHClass 96B → ~60B (接近 V8 ~54B)
```

### 总节省预估 (10,000 活跃 HClass 场景)

| 阶段 | HClass 大小 | 总内存 | 节省 |
|------|-----------|--------|------|
| 当前 | 120B | 1.14 MB | — |
| 第1批后 (AB) | 96B | 0.92 MB | 230 KB |
| 第2批后 (ABC) | 88B | 0.84 MB | 310 KB |
| Pointer Comp (E) | ~52B | 0.50 MB | 650 KB |
