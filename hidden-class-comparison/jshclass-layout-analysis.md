# ArkVM JSHClass 对象布局分析报告

> 来源: OpenHarmony `js_hclass.h:2214-2226`, V8 `src/objects/map.h (public)`, JSC `runtime/Structure.h`, Hermes `include/hermes/VM/HiddenClass.h`
> 字段大小均从 ACCESSORS 宏偏移量精确计算，非估算。

---

## 第一部分: JSHClass 布局全景

### 1.1 整体结构

JSHClass 是 ArkVM 中每个对象“属性布局”的描述符。当开发者在 ArkTS 中写 `class MyButton { title: string; onClick(): void {} }` 时，VM 内部会创建 JSHClass，记录这种对象有几个属性、属性在对象实例中的偏移，以及属性是否可枚举、可写。

当前 64 位源码中，每个 JSHClass 实例占 **88 字节**。Heap Snapshot 显示的 **0.09 KB** 与该大小一致：`88 / 1024 = 0.0859375 KiB`，界面保留两位小数后为 `0.09 KB`。Snapshot 中该列来自节点的 `self_size`（浅层大小），不包含 JSHClass 指向的 Layout、Transitions、EnumCache 等独立堆对象。

```
偏移   大小   字段                  
──────────────────────────────────── 
 0      8B   TaggedObjectHeader      
 8      4B   BitField               
12      4B   BitField1              
16      8B   Proto             
24      8B   Layout             
32      8B   Transitions       
40      8B   Parent            
48      8B   ProtoChangeMarker 
56      8B   ProtoChangeDetails
64      8B   EnumCache         
72      8B   DependentInfos    
80      8B   BitField2         
── 88B (DEFINE_ALIGN_SIZE)
```

`DEFAULT_CAPACITY_OF_IN_OBJECTS = 4` **不属于 JSHClass 自身布局**。它是创建普通对象的 JSHClass 时使用的默认参数，表示“这个 JSHClass 所描述的对象实例默认预留 4 个对象内属性槽”。这些槽位计入被描述对象实例的 `ObjectSize`，不计入 JSHClass 的 `JSHClass::SIZE`。`ObjectFactory::NewEcmaHClass` 分配 JSHClass 时明确使用 `classSize = JSHClass::SIZE`。

```text
JSHClass 描述符（固定 88B）
  ├─ ObjectSizeInWords：记录被描述对象实例的大小
  └─ InlinedPropsStart：记录实例内属性槽从哪里开始

被描述的对象实例（大小随对象类型和对象内属性数变化）
  ├─ 对象自身固定字段
  └─ 默认最多 4 个 in-object property slots（适用时）
```

Heap Snapshot 的取值链路为：`GenerateNode` → `TaggedObject::GetSize()` → 元类 JSHClass 的 `SizeFromJSHClass()` → `GetObjectSize()`。JSHClass 对象的元类记录的对象大小为 `JSHClass::SIZE`。序列化器把该值原样写入 `nodes[].self_size`，单位是字节。

### 1.2 逐字段详解

> 每条解释遵循：**产生阶段** (何时创建/谁写入) → **消费场景** (何时读取/影响什么) → **用户可感知行为** (开发者写什么代码会触发) → **证据** (源码行号)。

#### TaggedObjectHeader (0-8B)

- **产生阶段**: 当 VM 通过 `Heap::AllocateYoungOrHugeObject` 在 SemiSpace 中分配对象时写入。这是 VM 堆分配器为每个对象写入的元数据头，包含 mark bit (用于 GC 标记) 和指向自身 JSHClass 的反向指针
- **消费场景**: GC 遍历对象图时读取 mark bit 判断存活；`JSTaggedValue::IsJSHClass()` 通过读 header 判断对象类型
- **用户可感知**: 不可见——这是 VM 内部机制。用户代码中 `new MyButton()` 或 `JSON.parse()` 创建的对象都有这个 header

#### BitField (8-12B, uint32_t)

- **产生阶段**: 在 `JSHClass::Initialize()` 中根据 `JSType` 枚举值一次性设置。例如创建 `class MyButton` 的构造函数时，JSType 被设为 `JS_FUNCTION` 或 `JS_API_FUNCTION`
- **包含标志** (按 bit 位):
  - JSType (bits 0-7): `JS_OBJECT`, `JS_FUNCTION`, `JS_API_FUNCTION`, `JS_ARRAY`...
  - IsCallable (bit 8): 对象是否可调用 → 影响 `typeof obj === 'function'`
  - IsConstructor (bit 9): 是否可 new → 影响 `new obj()` 是否合法
  - IsExtensible (bit 10): 是否可添加新属性 → `Object.preventExtensions(obj)` 后为 false
  - IsPrototype (bit 11): 是否是原型对象 → 影响属性查找路径
  - ElementsKind (bits 12-16): `PACKED_SMI`, `HOLEY_DOUBLE` 等 → 影响数组访问优化路径
  - IsDictionary (bit 19): 是否已降级为字典模式 → 影响属性访问性能
- **消费场景**: 极高频率。每次 `obj.x` 访问的 IC (Inline Cache) 都需检查 `IsDictionary` 来决定走 fast path 还是 slow path
- **用户可感知**: 开发者调用 `Object.defineProperty(obj, 'x', {value: 1})` 时，若该 shape 是首次添加属性，会触发 HClass transition 并更新 BitField。当属性过多 (>1023) 时 `IsDictionary` 变为 true，属性访问从 O(1) 降级为 O(n)

```typescript
// 示例: 此代码触发 BitField 变化
let obj = { a: 1, b: 2 };     // HClass₁: IsDictionary=false
obj.c = 3;                      // HClass₂: NumOfProps 从 2 变为 3
obj.d = 4;                      // HClass₃: 再变...
// ...当属性超过 1023 个时:
// IsDictionary 变为 true, 所有后续属性访问走 hash 查找
```

#### BitField1 (12-16B, uint32_t)

- **产生阶段**: `JSHClass::Initialize()` 时根据对象类型计算。三个子字段均在初始化和 transition 时更新
- **子字段**:
  - NumberOfProps (bits 0-9): 当前 shape 的属性总数。最大 1023
  - InlinedPropsStart (bits 10-14): 首个 inline 属性在对象中的偏移 (word 单位)
  - ObjectSizeInWords (bits 15-29): 对象总大小 (word 单位)
- **消费场景**: `JSFunction::GetInlinedPropertyOffset(index)` 使用 `ObjectSizeInWords` 计算 `obj.x` 的实际内存偏移
- **用户可感知**: 开发者调用 `class MyButton { title = ''; onClick() {} }` 时，每个属性声明使 `NumberOfProps`+1。当属性超过 `InlinedPropsStart` 的位置时，新增属性存储在对象外部的 properties store 中 (类似 V8 的 "slow properties")

#### Proto (16-24B)

- **产生阶段**: 在 `CreateFunctionClass` 或 `Clone` 时从原型链复制。每个对象的 HClass 中 `Proto` 指向其原型的 HClass
- **消费场景**: 属性查找链的核心。`obj.toString()` → 若 `obj` 自身的 HClass 中没有 `toString` → 沿 `Proto` 链向上查找
- **用户可感知**: 这是 JavaScript 原型继承的基础。`class Dog extends Animal {}` 时，Dog 的构造函数 HClass 的 `Proto` 指向 Animal 的 prototype HClass

```typescript
// 原型链查找路径:
class Animal { walk() {} }
class Dog extends Animal { bark() {} }
let d = new Dog();
d.bark();   // 在 Dog.prototype HClass 中找到
d.walk();   // Dog HClass → Proto → Animal.prototype HClass 中找到
d.toString(); // 继续沿 Proto 链 → Object.prototype HClass
```

#### Layout (24-32B)

- **产生阶段**: `CreateLayoutInfo()` 创建 `LayoutInfo` (TaggedArray)，每个 inline property 记录属性名和属性标志
- **消费场景**: `for...in` 枚举 — `JSHClass::GetAllEnumKeys()` 遍历 Layout 获取所有可枚举键。JSON.stringify, Object.keys 也依赖 Layout
- **用户可感知**: 用户写 `for (let k in obj)` 时，VM 读取 `Layout` 来构建键列表。Layout 中的属性标志 (writable/enumerable/configurable) 决定该键是否出现在枚举结果中

#### Transitions (32-40B)

- **产生阶段**: 每次 `AddProperty` → `AddPropertyToNewHClass` → 生成新的 HClass Clone（当前为 88B） → 插入 transition 链表头
- **消费场景**: 后续代码对**另一个对象**执行相同的属性添加序列时，VM 沿 Transitions 链表查找是否已存在匹配的 shape。若存在则复用，否则创建新 HClass
- **用户可感知**: 

```typescript
let a = {}; a.x = 1;  // 创建 HClass₁ → HClass₂ (添加 "x")
let b = {}; b.x = 2;  // 遇到相同 pattern → 沿 Transitions 链表找到 HClass₂ → 直接复用
let c = {}; c.x = 3; c.y = 4; // 创建 HClass₁ → HClass₂ → HClass₃ (添加 "y")
```
- **性能特征**: 链表查找 O(n)，n = 当前 HClass 的 transition 分支数
- **证据**: `js_hclass.cpp:358-388`

#### Parent (40-48B)

- **产生阶段**: `Clone` 时设置 `newHClass->SetParent(oldHClass)`
- **消费场景**: GC tracing 中需要从子 HClass 追溯到父 HClass，确保 transition 链上所有对象被正确标记。仅在 GC 期间访问
- **用户可感知**: 不可见。不影响应用层行为

#### ProtoChangeMarker (48-56B) + ProtoChangeDetails (56-64B)

- **产生阶段**: `MarkProtoChanged` — 当原型被修改时 (如 `Class.prototype.newMethod = ...`) 在原型 HClass 上设置标记
- **消费场景**: for-in 枚举前检查 `IsEnumCacheValid`。若原型被修改，EnumCache 失效，枚举需要重新构建键列表而非使用缓存
- **用户可感知**:

```typescript
// 场景: 猴子补丁 (monkey-patching)
class Foo { bar() {} }
let f1 = new Foo(); for (let k in f1) { /* EnumCache 构建 */ }
Foo.prototype.baz = function() {};  // ← 触发 MarkProtoChanged
let f2 = new Foo(); for (let k in f2) { /* EnumCache 失效, 重新构建 */ }
```
- **两个字段的理由**: ProtoChangeMarker 是被修改标记本身 (一个 TaggedObject), ProtoChangeDetails 记录修改的详情 (哪个属性被添加/删除)

#### EnumCache (64-72B)

- **产生阶段**: `GetOrCreateEnumCacheFromHClass` — `for...in` 首次在具有同一种属性布局的对象上执行时，创建 EnumCache 对象并填入缓存键列表。“同一种属性布局”是指属性名、添加顺序和属性特征相同；VM 内部通常称为相同 shape 或相同 JSHClass
- **内容已惰性**: `JSHClass::Initialize` 时设为 `Null()`。仅在首次 for-in 时才真正分配
- **消费场景**: `for...in` 是 ArkTS/JavaScript 中枚举对象可枚举属性名的语法。后续对相同属性布局的对象执行 `for...in` 时，VM 可直接通过 `GetEnumCacheOwn` 取得已缓存的键列表，无需重新遍历 Layout。JSON 序列化路径也会检查该缓存
- **用户可感知**: 同一种属性布局的对象第一次枚举属性时需要生成键列表，后续枚举可以复用；修改原型后，缓存失效并重新生成
- **字段槽不惰性**: 虽然内容惰性，但 **8B 的指针槽始终在 JSHClass 中**。这就是优化空间——如果移到 side table，不常做 for-in 的 HClass 可以节省这 8B
```typescript
const a = { id: 1, name: 'A' };
const b = { id: 2, name: 'B' }; // 属性名和添加顺序与 a 相同，可复用同一属性布局

for (const key in a) {          // 首次为该布局生成可枚举键列表：id、name
  console.info(key);
}
for (const key in b) {          // 可复用缓存的键列表
  console.info(key);
}
```

#### DependentInfos (72-80B)

- **产生阶段**: JIT 编译器 (Baseline/优化编译器) 生成机器码后，将生成的代码绑定到特定的 HClass。存储在 `DependentInfos` 中
- **消费场景**: 当 HClass 发生变更 (新增属性、降级为字典等)，VM 通过 `DependentInfos` 链通知所有依赖的 JIT 代码失效 (deoptimization)
- **用户可感知**: 用户写热循环时触发 JIT 编译。如果后续代码修改了对象的 shape (如循环中添加新属性)，JIT 代码被 deopt → 回退到 interpreter
- **为什么在 JSHClass 内联**: deopt 通知需要快速定位所有依赖代码。移到 side table 意味着需要哈希表查找

#### BitField2 (80-88B, uint64_t)

- **产生阶段**: `JSHClass::Initialize` + transition 过程中设置额外标志
- **内容**: 包括 ASAN 校验位、`IsJSShared` (共享堆标记)、`IsStable` (是否可优化) 等
- **消费场景**: ASAN 模式下校验对象访问合法性；`IsJSShared` 判断对象是否在跨线程共享堆中

---

## 第二部分: 竞品对比

### 2.1 竞品基础信息

| 竞品 | 维护方 | 主要设备 | 开源仓库 |
|------|--------|---------|---------|
| **V8** | Google | Chrome, Android WebView, Node.js, Deno | chromium/v8 |
| **JSC (JavaScriptCore)** | Apple | Safari, iOS WKWebView, macOS | WebKit |
| **Hermes** | Meta | React Native (Android/iOS) | facebook/hermes |
| **ArkVM** | 华为 | HarmonyOS 全设备 (轻设备→手机→平板) | gitcode.com/openharmony |

### 2.2 总体差距汇总

```
                 V8 Map    JSC Structure   Hermes HC    ArkVM JSHClass
─────────────────────────────────────────────────────────────────────
描述符自身:       ~42B         ~64B           ~32B          88B
对象内属性槽:     不计入 Map    不计入 Structure 不计入 HC     不计入 JSHClass
指针宽度:         4B (cmp)     8B             0B (ID)       8B
ProtoChange*:     0B (cell)   0B              0B           16B
EnumCache:        内联 4B      无             无            内联 8B
DependentInfos:   内联 4B      内联 8B         无            内联 8B
─────────────────────────────────────────────────────────────────────
说明:              各引擎数值必须在相同版本、架构和编译配置下实测后再计算比例
```

### 2.3 V8 Map 详解

#### 2.3.1 Prototype Validity Cell — V8 如何用 0 额外空间实现 ProtoChange

**ArkVM 做法**: ProtoChangeMarker (8B) + ProtoChangeDetails (8B) = 16B 存储在 JSHClass 内联字段中。

**V8 做法**: 在 Map 中用 `prototype_validity_cell` (已经占用了一个 4B compressed ptr 字段) 同时承载「原型有效性」和「原型变更检测」。原始类型 `Cell` 是一个单字段对象 (仅含一个 Smi/ptr)，所有共享同一原型的 Map 指向**同一个 Cell 对象**。当原型被修改时，只需将该 Cell 的值从 `Smi::FromInt(0)` 改为 `Smi::FromInt(1)`——所有指向此 Cell 的 Map 的 EnumCache 自动感知到失效。

```cpp
// V8 等效伪代码 (src/objects/map.cc, 简化)
void Map::SetPrototype(Handle<JSObject> prototype) {
    Handle<Cell> cell = factory->NewCell(Smi::FromInt(0));
    set_prototype_validity_cell(*cell);  // 已内联在 Map 中，无额外字段
}
// 原型变更时:
void JSObject::InvalidatePrototypeChains() {
    cell->set_value(Smi::FromInt(1));    // 一次性, 所有共享 Map 同时失效
}
```

**得失**: V8 用共享 Cell 的方式节省了 16B/Map，但代价是原型变更时需要遍历所有指向该 Cell 的 Map (通过 weak list)。ArkVM 的独立字段方案在原型变更时只需要写一个字，但增加了每个 HClass 16B 的固定开销。

#### 2.3.2 Dependent Code — V8 的外置策略

**ArkVM 做法**: `DependentInfos` (8B) 内联在 JSHClass 中。

**V8 做法**: `dependent_code` 同样是内联在 Map 中的 4B 指针，但其指向的 `DependentCode` 是 `WeakArrayList`——一个 GC 可自动回收弱引用的数组。当优化代码被 GC 回收时，对应的 entry 自动清理。更重要的是，V8 Map 的总大小仅 ~42B，即使这个字段内联，总体开销仍远小于 ArkVM。

**得失**: V8 用 `WeakArrayList` 而非独立对象降低了 GC 管理的复杂度。ArkVM 可以保持 `DependentInfos` 内联，但与 ProtoChange* 的累计冗余 (24B) 是主要问题。

#### 2.3.3 TransitionArray 树形结构 — V8 如何做到 O(1)

**ArkVM 做法**: Transitions 是单向链表 → 查找 O(n)。

**V8 做法**: `TransitionArray` 是一个基于属性名的散列表。每个 Map 的 `transitions` 字段指向一个 `TransitionArray`，其中以属性名为 key 存储过渡目标 Map。

```
ArkVM (链表):
  HClass₀ → [Transitions] → HClass₁("x") → HClass₂("y") → HClass₃("z")
  查找 "z": 遍历 3 步 O(n)

V8 (散列树):
  Map₀ → TransitionArray[hash("x")→Map₁x, hash("y")→Map₁y, hash("z")→Map₁z]
  查找 "z": hash("z") → 1 步 O(1)
```

**得失**: V8 的树形结构查找更快，且 TransitionArray 中的目标 Map 共享同一个 `DescriptorArray` (属性描述数组)。ArkVM 每次 Clone 可能创建独立的 Layout。

### 2.4 JSC Structure 详解

**维护方**: Apple (WebKit 项目)。用于 Safari、WKWebView (iOS/macOS 上所有第三方浏览器的内核)。

**核心差异**: 在当前文档引用的结构边界下，JSC Structure 记为约 64B，ArkVM JSHClass 源码值为 88B；该近似值不能替代同配置实测，主要因为：
- 无 ProtoChangeMarker/Details (用 1 bit 标志 + transition watchpoint 机制)
- 无 EnumCache 内联 (for-in 走 PropertyTable)
- 无 DependentInfos (JIT watchpoint 在 Structure 外部)
- 使用 `PropertyTable` 共享属性存储 (多个 Structure 可指向同一 PropertyTable)

**用户可感知差异**: JSC 的 Structure transition 通过 `m_transition` 单指针完成，创建新 Structure 时不复制 PropertyTable (除非属性列表确实不同)。这类似于 V8 的 DescriptorArray 共享策略。

### 2.5 Hermes HiddenClass 详解

**维护方**: Meta (Facebook)。专为 React Native 移动端设计，无 JIT。

**核心差异**: Hermes HiddenClass (~32B) 是极致压缩设计：
- 无任何指针字段 (属性名用 4B SymbolID 替代 8B 指针)
- 无 ProtoChange/EnumCache/DependentInfos (无 JIT, 无需相关元数据)
- for-in 每次遍历属性列表 (无缓存，但属性列表短)
- Transition 信息在 Property Map 中而非 HiddenClass 自身

**适用限制**: Hermes 的设计目标就是低内存/无 JIT，不适用于需要高性能 JIT 的场景。ArkVM 需要同时支持 JIT 和低内存，复杂度更高。

---

## 第三部分: 优化方案

### 方案 A: ProtoChange 字段合并 (−16B)

- **预估效果**: 每个 JSHClass 的内联大小减少 16B，即 88B → 72B，降幅为 18.2%。按京东场景观测到的 **80,000+ 个 JSHClass** 计算，80,000 个对象的内联字段毛节省为 `80,000 × 16B = 1,280,000B = 1.22MiB`；对象数超过 80,000 时按每增加 10,000 个 JSHClass 再减少约 0.153MiB 线性增加。ProtoChangeDetails side table 的表项和哈希桶占用需从毛节省中扣除，因此 1.22MiB 是内联字段减少量，不是进程内存净下降量。ProtoChangeMarker 合并为 BitField2 中 1 bit 标志，ProtoChangeDetails 仅在发生原型变化时进入 side table
- **改动工作量**: 约 3-5 人天。涉及 `js_hclass.h` (移除 2 字段), `js_hclass.cpp` (访问路径改为 BitField2 flag + hash map), `js_hclass-inl.h` (MarkProtoChanged 路径)
- **兼容性分析** (用户视角):
  - **新旧镜像**: 不涉及字节码格式变更。老版本镜像中的 JSHClass 访问路径通过函数调用抽象 → 无需镜像升级
  - **机型隔离**: 无影响。所有机型统一生效
  - **SDK/API 版本**: 不影响任何公开 API
- **稳定性影响**: 低。ProtoChange 仅原型修改时触发 (rare event)。`MarkProtoChanged` 从直接字段访问改为 flag check + 条件 hash map 查找 → 额外开销 <10ns

### 方案 B: DependentInfos 外移 (−8B)

- **预估效果**: 每个 JSHClass 的内联大小减少 8B，即 88B → 80B，降幅为 9.1%。按 80,000 个 JSHClass 计算，内联字段毛节省为 `640,000B = 0.61MiB`；每增加 10,000 个 JSHClass 再减少约 0.076MiB。仅被 JIT 优化过的 JSHClass 在 side table 中产生 entry，净节省量等于 0.61MiB 减去 side table、弱引用和同步结构的实际占用，需通过改动后的 Heap Snapshot 与进程内存数据测量
- **改动工作量**: 约 5-8 人天。涉及 JSHClass 字段移除 + JIT deoptimization 通知路径 + GC 对 side table 的弱引用管理
- **兼容性分析** (用户视角):
  - **新旧镜像**: JIT 代码本身绑定到特定 HClass。老镜像上不启用 JIT → DependentInfos 为空 → 移除后无影响。新镜像使用 side table 查找 → 功能等价
  - **机型隔离**: 可以在 `config.h` 中按设备内存级别控制。低内存设备 (`< 4GB`): 开启外置; 高内存设备: 保持内联以获得最快 deopt 通知
  - **编译开关**: 通过 `ENABLE_MEMORY_OPTIMIZATION` 宏控制 → 同一份源码可编译出不同配置
- **稳定性影响**: 中等。deopt 通知是 JIT 稳定性的关键路径。需要在 side table 的读写中确保线程安全

### 方案 C: EnumCache Side Table (−8B)

- **预估效果**: 每个 JSHClass 的内联大小减少 8B，即 88B → 80B，降幅为 9.1%。按 80,000 个 JSHClass 计算，内联字段毛节省为 `640,000B = 0.61MiB`；每增加 10,000 个 JSHClass 再减少约 0.076MiB。仅实际执行过 `for...in` 或相关枚举路径的 JSHClass 在 side table 中产生 entry，净节省量取决于命中该路径的 JSHClass 比例以及 side table 每项开销
- **改动工作量**: 约 8-12 人天。需修改 Baseline JIT stub (`builtins_object_stub_builder.cpp`) 中的 `GetOrCreateEnumCacheFromHClass` → 从直接偏移访问改为 runtime call
- **兼容性分析** (用户视角):
  - **新旧镜像**: 不涉及字节码变更。老镜像中 for-in 仍走内联字段路径。新镜像中首次 for-in 触发 side table 创建 → 后续访问快
  - **机型隔离**: 可针对低内存设备开启外置。高内存设备保持内联获取最大 for-in 性能
  - **API 兼容**: 不影响 `for...in`, `Object.keys`, `JSON.stringify` 的行为
- **稳定性影响**: 中等。Baseline JIT stub 修改需充分测试 for-in 在各种 HClass 状态下的正确性 (空对象、字典模式、原型链长链等)

### 方案 D: Transition 树替代链表 (性能优化)

- **预估效果**: 目标是把多分支 Transition 查找从链式遍历改为按属性键索引，并通过描述符共享减少重复 Layout。该方案不删除 JSHClass 的 8B Transitions 指针，不能直接按 `80,000 × 字段大小`计算收益；需要采集京东场景的 Transition 节点数、链长、Layout 节点数和共享率后，分别测量查找耗时及附属节点内存
- **改动工作量**: 约 2-3 人月 (核心数据结构变更 + GC 适配 + JIT stub 适配)
- **兼容性分析**: 核心数据结构变更 → 需全量回归测试
- **稳定性影响**: 高。Transition 是 VM 最核心的数据结构之一

### 方案 E: Pointer Compression (长线)

- **预估效果**: 若对象头中的类指针及 JSHClass 的 8 个 Tagged 指针都由 8B 压缩为 4B，JSHClass 理论字段宽度减少 36B，即 88B → 52B。按 80,000 个 JSHClass 计算，JSHClass 部分的理论毛节省为 `2,880,000B = 2.75MiB`。该数值未计对齐、压缩指针基址、解码辅助结构和全 VM 布局约束，只能作为完成具体设计前的字段宽度上限；全 VM 其他对象的收益不在这里估算
- **改动工作量**: 团队级项目 (类似 V8 2019 年的 ptr-compr 改造)。涉及 GC 标记/压缩、interpreter 指针解引用、JIT codegen、跨进程通信中的所有 64-bit 指针 → 32-bit 偏移量转换
- **兼容性分析**:
  - **新旧镜像**: 需要镜像升级。Pointer compression 改变了对象内存布局，老镜像中的 64-bit 指针不能被新 VM 直接解析
  - **32-bit 设备**: 天然兼容 (32-bit 设备上指针本就是 32-bit)
  - **64-bit 设备**: 引入 4GB 堆上限 (compressed pointer 只能索引 4GB 内存空间)。对大部分鸿蒙应用场景足够
- **稳定性影响**: 极高。需全量回归测试全 VM 组件

### 方案 F: JSApiFunction 裁剪 (已实现)

- **预估效果**: API 函数对象按当前分析边界每个减少约 32B。该方案优化的是 JSApiFunction，不减少 JSHClass 的 88B；京东场景只有 JSHClass 数量，不能据此推导该方案收益。若 Snapshot 中 API 函数对象数量为 `N`，对应毛节省计算式为 `N × 32B`
- **当前状态**: ✅ 已在 `ENABLE_API_FUNCTION_OPTIMIZATION` + `ENABLE_MEMORY_OPTIMIZATION` 双宏路径下实现
- **覆盖范围**: `New`, `NewConcurrent`, `NewClassFunction` — 所有 N-API 函数创建路径

### 推荐实施顺序

```
第1批 (低风险, 1-2周):
  ├─ 方案 A: ProtoChange 合并    −16B  [改 3 文件, 无 JIT stub 改动]
  └─ 方案 B: DependentInfos 外移  −8B  [config.h 宏隔离, 可按机型开启]

第2批 (中等风险, 2-4周):
  └─ 方案 C: EnumCache side table  −8B  [需改 Baseline JIT stub]

长期规划:
  ├─ 方案 D: Transition 树         架构优化 [2-3 人月, 下个大版本]
  └─ 方案 E: Pointer Compression   −36B     [全 VM 改造, 版本级项目]

已落地:
  └─ 方案 F: JSApiFunction 裁剪     −32B/函数 [已合入主线]
```

### 京东场景（80,000+ JSHClass）效果汇总

以下计算以 80,000 个 JSHClass 为下界。当前 JSHClass 自身浅层内存为 `80,000 × 88B = 7,040,000B = 6.71MiB`。表中的“毛节省”只计算从每个 JSHClass 内联布局中删除的字节；使用 side table 的方案还需扣除表项、哈希桶、弱引用和同步结构占用。

| 方案/阶段 | 单个 JSHClass | 80,000 个合计 | 相对当前毛节省 | 是否可由现有数据计算净收益 |
|---|---:|---:|---:|---|
| 当前 | 88B | 6.71MiB | — | Snapshot 已显示单个约 0.09KB |
| 方案 A：ProtoChange 外移 | 72B | 5.49MiB | **1.22MiB** | 否；需扣除仅在原型变化时产生的 side table 项 |
| 方案 B：DependentInfos 外移 | 80B | 6.10MiB | **0.61MiB** | 否；需统计被 JIT 优化的 JSHClass 比例和 side table 项 |
| 方案 C：EnumCache 外移 | 80B | 6.10MiB | **0.61MiB** | 否；需统计执行过属性枚举的 JSHClass 比例和 side table 项 |
| 方案 A+B | 64B | 4.88MiB | **1.83MiB** | 否；需扣除两类 side table 开销 |
| 方案 A+B+C | 56B | 4.27MiB | **2.44MiB** | 否；需扣除三类 side table 开销 |
| 方案 D：Transition 数据结构 | JSHClass 指针槽不变 | 不能只由 JSHClass 数量计算 | 待测 | 需 Transition/Layout 节点数量、链长和共享率 |
| 方案 E：Pointer Compression | 理论 52B | 理论 3.97MiB | 理论上限 **2.75MiB** | 否；需完成布局、对齐和辅助结构设计 |
| 方案 F：JSApiFunction 裁剪 | JSHClass 仍为 88B | 不能由 JSHClass 数量计算 | `API函数数 × 32B` | 需 API 函数对象数量 |

当 JSHClass 实际数量高于 80,000 时，方案 A 每增加 10,000 个对象增加约 0.153MiB 毛节省，方案 B 或 C 各增加约 0.076MiB，方案 A+B+C 增加约 0.305MiB。

<!-- BEGIN HERMES REVIEW APPENDIX 2026-08-12 -->
## 复核意见（2026-08-12）

- **结论（P0）**：88B/self_size 可保留；正文仍使用过期 80,000 基数，并错误描述 transition、Parent、Proto、Layout sharing 和竞品尺寸，不能支撑实施或对外比较。
- **数据/源码事实**：Top13 当前有 819,497 个 hclass，而正文 `jshclass-layout-analysis.md:286-371` 仍按 80,000 汇总。`TransitionsDictionary` 是哈希表（`transitions_dictionary.h:25-97`），Clone 明确复用 Layout（`js_hclass.cpp:227-248`）；正文 `:93,115-124,240-254` 的“Proto 指向原型 HClass、线性链、独立 Layout”均不成立。
- **风险或反例**：Parent“仅 GC”、属性阈值、V8/JSC/Hermes 精确尺寸、`<10ns` side-table 和 3-5 人天缺一手证据。老镜像不会因 C++ accessor 抽象自动兼容；generated code、snapshot/serializer 仍绑定 offset。三个 side table 的净收益不能按字段宽度相加。
- **放行条件**：按当前源码重写字段生产/消费和 transition/Layout；竞品绑定同 revision/架构/config 的 generated layout；统一使用 Top13 人口与真实容器 capacity，补 weak/ephemeron、local/shared、AOT/JIT direct-offset 和 clean 性能/PSS 证据。
<!-- END HERMES REVIEW APPENDIX 2026-08-12 -->
