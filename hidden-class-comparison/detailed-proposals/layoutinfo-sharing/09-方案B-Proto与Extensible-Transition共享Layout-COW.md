# 方案 B：Proto / Extensible Transition 共享 Layout + COW 设计评审

> 本文档归档 `TransitionProto` 与 `TransitionExtension` 的直接 Layout 复用方案。方案不使用 exact-match table 或 weak table，但必须完整实现 Layout type-state、写时复制和所有写入口收口；仅删除两处 `CopyLayoutInfo` 不构成可用实现。

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 归档日期 | 2026-08-28 |
| 方案范围 | LocalHeap `TransitionProto`、`TransitionExtension` 及其 Layout 写安全依赖 |
| 评审维度 | 架构、流程、数据结构、兼容性、性能、风险、测试、回滚 |
| 实现状态 | 方案归档；未实施，候选收益须由创建路径标签与 clean A/B 验证 |

---

## 1. 概述

### 1.1 背景

`JSHClass::Clone` 已复用源 HClass 的 Layout 指针。`TransitionExtension` 与 `TransitionProto` 在 clone 后又显式调用 `CopyLayoutInfo`，使新旧 HClass 获得内容相同但 identity 不同的 Layout：

```text
source HClass --Layout--> L0
       |
       +-- Clone ----------------------> target HClass --Layout--> L0
       |
       `-- CopyLayoutInfo(L0) ---------> target HClass --Layout--> L1

L0 与 L1 的 capacity、NumberOfElements、key 槽和 Attr 槽相同。
```

两个 transition 只改变 HClass 的 prototype 或 extensible 状态，不改变属性 Layout 内容。直接保留 clone 后的共享指针可以避免 L1 分配，但 LayoutInfo 存在 `AddKey`、Attr、TrackType、PGO 等原地写入口，因此共享对象必须进入 immutable type-state，后续写入必须先按 owner 脱离。

### 1.2 目标

| 目标 | 验收口径 |
|---|---|
| 消除两个 transition 的防御性 Layout 复制 | 命中路径不调用 `CopyLayoutInfo` |
| 保持 HClass 状态独立 | source/target 的 proto、extensible、transitions、dependent info 等仍独立 |
| 保证共享 Layout 不被原地写 | immutable 直写在 debug/release 均被阻断 |
| 保持 TrackType/PGO 家族语义 | 需要共同变化的 owner 成组脱离并保持一致 |
| 不引入查表 | 无 exact-match、hash、weak table 或跨家族内容匹配 |
| 可回滚 | build/runtime 双开关默认关闭；关闭时保留现有 copy |
| 可观测 | avoided-copy、COW、批量 owner 数、拒绝原因可汇总 |

### 1.3 范围

**范围内**：

- LocalHeap fast-property HClass 的 `TransitionProto` 与 `TransitionExtension`；
- 现有 `TAGGED_ARRAY`（mutable）/ 新增 `IMMUTABLE_LAYOUT_INFO` type-state；
- LocalHeap `READ_ONLY_SPACE` Layout 作为既有 immutable 状态，写入时直接 COW，禁止切换其对象 HClass；
- append-only immutable JSType、`IsTaggedArray` 分类、GC visitor、dump/snapshot type switch 的配套接入；
- full-physical copy helper；
- 所有 LocalHeap Layout mutation 调用点的 owner-aware COW；
- TrackType/PGO/representation/metadata 等批量传播路径；
- Feature Flag、计数器、断言、回滚与验证。

**范围外**：

- 跨内容、跨 transition family 的 canonicalization；
- exact-match table、weak table、hash；
- SharedHeap / Sendable Layout；
- dictionary property storage；
- HClass 本身去重；
- `OptimizePrototypeForIC`、representation transition 等其他 copy 路径的 copy 消除；
- 跨 VM、跨 Realm、跨进程共享。

---

## 2. 现有架构分析

### 2.1 现有架构图

```text
TransitionExtension                         TransitionProto
  |                                           |
  +-- Find existing transition                +-- Find existing transition/AOT transition
  |     `-- hit: return                        |     `-- hit: return
  |                                           |
  +-- JSHClass::Clone(source)                  +-- JSHClass::Clone(source)
  |     `-- Layout 暂时复用 source             |     `-- Layout 暂时复用 source
  +-- SetExtensible(false)                     +-- SetPrototype(proto)
  +-- CopyLayoutInfo                           +-- CopyLayoutInfo
  +-- SetLayout(copy)                          +-- SetLayout(copy)
  `-- Add transition                           `-- Add proto transition
```

### 2.2 现有写入模型

LayoutInfo 是 TaggedArray 的私有解释，每个属性占 key 与 Attr 两槽。冻结源码中存在以下 mutation 类别：

| 类别 | 典型入口 |
|---|---|
| 构建/追加 | `SetNumberOfElements`、`SetPropertyInit`、`AddKey`、`SetSortedIndex` |
| 属性元数据 | `SetNormalAttr`、`SetIsNotHole` |
| 类型演化 | `UpdateTrackTypeAttr`、representation 更新 |
| PGO | `SetIsPGODumped`、dump/update descriptor |
| 复制后写 | runtime stub、constructor HClass correction、AOT/PGO restore |
| family grow | `ExtendLayoutInfo`、`CopyAndReSort` 后继续 AddKey |

现有方法通常只持有 `LayoutInfo *`，无法自行确定需要切换哪一个 owner HClass；COW 必须在调用方取得 Layout 指针之前完成。

### 2.3 现有架构问题

| 问题 | 影响 |
|---|---|
| 两个 transition 改 HClass 状态但复制完整 Layout | 产生内容相同的数组与 GC 对象 |
| Layout 写 API 不带 owner | 不能在方法内部自动完成 owner 指针切换 |
| TrackType 沿 transition 子树传播 | 单 owner COW 会破坏本应共同演化的家族语义 |
| PGO 位原地写在 Attr 中 | 直接共享后会跨 owner传播状态 |
| transition family 可能共享可增长数组 | 将对象冻结后，后续 AddKey 必须先脱离 |
| dump 只能显示终态 identity | 无法仅凭相同内容证明对象来自哪个 copy 调用点 |

---

## 3. 目标架构设计

### 3.1 目标架构图

```text
TransitionProto / TransitionExtension
  |
  +-- flag off ----------------------------> 现有 Clone + CopyLayoutInfo
  |
  `-- flag on
        +-- JSHClass::Clone(source)
        +-- 改 target 自身 proto/extensible 状态
        +-- MakeImmutableLayout(source.layout)
        |     `-- 所有现有 owner 看到同一 immutable type-state
        +-- target 保留相同 Layout 指针
        `-- 登记 HClass transition

任意后续 Layout mutation
  -> 收集语义上共同变化的 owner 集合
  -> EnsureMutableLayoutForOwners(owners)
       +-- mutable 且独占/合法：直接返回
       `-- immutable：复制完整物理槽，owner 切换到 mutable copy
  -> 在 mutable copy 上执行原写操作
```

### 3.2 架构设计原则

| 原则 | 说明 |
|---|---|
| 关系给出共享 | source/target transition 关系直接证明内容相同，不查内容表 |
| immutable 后共享 | 一旦新增 owner，共享 Layout 立即进入 immutable type-state |
| owner-aware COW | 写前先切换 owner，再取得可写 Layout 指针 |
| full-physical copy | 复制 capacity、ExtraLength 和全部物理 key/Attr/slack 槽 |
| family 语义优先 | TrackType/PGO 等传播路径先确定 owner 集合，再成组脱离 |
| SharedHeap 隔离 | 仅 LocalHeap；shared 路径使用其现有机制 |
| 读取零改动 | `JSHClass::LAYOUT_OFFSET`、TaggedArray 格式和读取 API 不变；type predicate 识别两种 Layout type-state |
| 不完整实现拒绝 | 写入口清单未闭合时不得启用 runtime flag |

### 3.3 组件关系

| 组件 | 职责 | 变更 |
|---|---|---|
| JSType / JSHClass predicates | 以现有 TAGGED_ARRAY 表示 mutable；新增一个 append-only immutable type | 增加枚举与 `IsTaggedArray` case，不进入 `IsCOWArray` |
| GlobalEnvConstants / ObjectFactory | 提供 immutable Layout HClass；mutable 继续使用现有 TaggedArrayClass | 只增加一个同布局 type-state 根 |
| LayoutInfo | 暴露只读状态查询；写方法校验 mutable | 不改变实例字段 |
| GC / dump / snapshot | 按 TaggedArray 相同范围扫描并识别类型 | 接入所有 JSType switch |
| JSHClass | transition 直接共享；提供 owner-aware COW 调用 | 修改两个 transition 与写调用点 |
| ObjectFactory | 完整物理复制并创建 mutable Layout | 增加 copy helper |
| TrackType/PGO | 收集 owner、成组脱离、再传播 | 重构传播入口 |
| JSOptions / FeatureConfig | build/runtime 双开关 | 默认关闭 |
| 统计模块 | avoided copy、COW 与 fanout 指标 | 汇总输出 |

---

## 4. 流程设计

### 4.1 TransitionExtension 流程

```text
TransitionExtension(source)
  |
  +-- existing transition hit -> 返回 existing HClass
  |
  +-- flag off -> 现有 Clone + SetExtensible(false) + CopyLayoutInfo
  |
  `-- flag on
        +-- source 不属于 LocalHeap fast-property 准入域 -> 现有路径
        +-- target = Clone(source)
        +-- target.SetExtensible(false)
        +-- FreezeLayoutForDirectSharing(source, target)
        |     +-- writable TAGGED_ARRAY -> 切 IMMUTABLE_LAYOUT_INFO
        |     +-- IMMUTABLE_LAYOUT_INFO -> 保持
        |     `-- READ_ONLY_SPACE Layout -> 保持对象/HClass，按既有 immutable 处理
        +-- target.layout 保留 source.layout identity
        `-- AddExtensionTransitions
```

### 4.2 TransitionProto 流程

```text
TransitionProto(source, proto, isChangeProto)
  |
  +-- existing/AOT transition hit -> 返回 existing HClass
  |
  +-- flag off -> 现有 Clone + SetPrototype + CopyLayoutInfo
  |
  `-- flag on
        +-- source 不准入 -> 现有路径
        +-- target = Clone(source)
        +-- target.SetPrototype(proto, isChangeProto)
        +-- FreezeLayoutForDirectSharing(source, target)
        |     +-- writable TAGGED_ARRAY -> 切 IMMUTABLE_LAYOUT_INFO
        |     +-- IMMUTABLE_LAYOUT_INFO -> 保持
        |     `-- READ_ONLY_SPACE Layout -> 保持对象/HClass，按既有 immutable 处理
        +-- target 保留 source.layout identity
        `-- AddProtoTransitions
```

HClass 的 prototype、extensible、transitions、parent、proto-change marker 与 dependent info 仍按现有 clone/transition 逻辑处理；只省 Layout copy。

### 4.3 单 Owner COW 流程

```text
准备写 owner.layout
  |
  +-- layout type == TAGGED_ARRAY 且 region 可写
  |     `-- 返回当前 mutable Layout
  |
  `-- layout type == IMMUTABLE_LAYOUT_INFO 或 region == READ_ONLY_SPACE
        +-- CopyFullPhysicalLayout(layout, TAGGED_ARRAY)
        |     +-- capacity 不变
        |     +-- NumberOfElements/ExtraLength 不变
        |     `-- 2 * capacity 全部槽逐一复制
        +-- owner.SetLayout(copy)
        `-- 返回 copy

调用方随后才执行 AddKey / SetNormalAttr / SetSortedIndex / ...
```

`EnsureMutableLayout` 的参数必须包含 owner HClass。接受裸 `LayoutInfo *` 并在内部猜 owner 的接口不允许进入实现。

### 4.4 多 Owner / Family COW 流程

```text
TrackType、PGO 或 family 传播准备写入
  -> 按现有 transition 子树规则收集目标 HClass 集合
  -> 按 (old Layout identity, 目标新状态) 分组
  -> 每组分配一个 mutable full-physical copy
  -> 将该组全部 owner 切换到同一 copy
  -> 在 copy 上执行一次状态更新
  -> 非目标 owner 保持指向旧 immutable Layout
```

同一逻辑状态只创建一份 copy；不得对目标 owner 逐个复制，也不得把非目标分支带入传播。

### 4.5 AddProperty / Grow 流程

```text
AddPropertyToNewHClass(parent, child, key, attr)
  -> child 由 Clone 获得 parent.layout
  -> child.layout immutable ?
       yes -> 仅 child 先 COW
       no  -> 执行现有逻辑
  -> NumberOfElements 与 offset 不匹配：CopyAndReSort
  -> capacity 不足：ExtendLayoutInfo
  -> AddKey
  -> AddTransitions
```

父 HClass 始终保留旧可见属性数。child 的 COW 必须发生在 `AddKey`、`SetNumberOfElements` 或 sorted index 写入之前。

### 4.6 PGO 与 Attr 更新流程

以下路径必须在写前取得 owner 或 owner 集合：

- root/child HClass PGO dump 与 update；
- `UpdateTrackTypeAttr` 的 transition 子树传播；
- representation change；
- `UpdatePropertyMetaData`；
- `MergeRepresentation`；
- `CorrectConstructorHClass`；
- runtime stub 的 copy-and-update；
- AOT/PGO HClass restore 中的 Layout 追加或修正。

PGO dump 的 `IsPGODumped` 位不是只读操作，不能绕过 COW。若 PGO 语义要求同一 family 共同置位，使用 §4.4 的批量流程。

### 4.7 Type-State 转换与 GC

```text
TAGGED_ARRAY（现有 mutable Layout）
  --首次 direct-share publish：对象切换 HClass--> IMMUTABLE_LAYOUT_INFO

IMMUTABLE_LAYOUT_INFO
  --owner mutation--> 分配新的 TAGGED_ARRAY mutable copy

READ_ONLY_SPACE Layout（既有、物理只读）
  --direct-share publish--> 保持原对象与 HClass
  --owner mutation--------> 分配新的 TAGGED_ARRAY mutable copy
```

- mutable 沿用现有 `JSType::TAGGED_ARRAY`；只新增一个 append-only `IMMUTABLE_LAYOUT_INFO`，禁止插入现有枚举中间导致旧 JSType 数值整体移动；
- mutability 判定同时检查 JSType 与 Region：只有可写 Region 中的 `TAGGED_ARRAY` 是 mutable；`IMMUTABLE_LAYOUT_INFO` 或 `Region::InReadOnlySpace()` 均为 immutable；
- `READ_ONLY_SPACE` Layout 不执行 `MakeImmutable`，不修改对象 HClass；其现有 GC/snapshot 语义保持，owner 写入前复制到可写 LocalHeap `TAGGED_ARRAY`；
- `JSHClass::IsTaggedArray()` 必须对 immutable type 返回 true，使 `LayoutInfo::Cast` 合法；`IsCOWArray()` 必须保持 false，避免触发普通数组元素 COW 语义；
- type-state 仅替换 Layout 对象的 HClass；实例大小、`TaggedArray::DATA_OFFSET` 和槽格式相同；
- immutable HClass 使用与 `TAGGED_ARRAY` 相同的 variable-length GC visitor，扫描 `[DATA_OFFSET, DATA_OFFSET + Length)`；
- 转 immutable 在 VM mutator 的 transition 操作内完成，并由 handle scope 保护；发布顺序为“Layout 对象换 immutable HClass -> target 保留该 Layout -> 登记 HClass transition”，禁止先让 target 可见；
- owner `SetLayout` 使用现有 synchronized accessor 与写屏障；
- 不增加 weak 引用或 native 表；
- 旧 immutable Layout 的存活由剩余 owner 强引用决定；最后 owner 死亡后由 GC 正常回收。

### 4.8 写入口门禁

实现阶段对冻结 revision 重新机械扫描：

1. `LayoutInfo` 全部 mutation 方法声明与调用点；
2. 通过 `TaggedArray` cast 或基类 API 对 Layout 槽的直接写；
3. `SetLayout` 后紧邻的 Attr/Key 更新；
4. `CopyLayoutInfo`、`ExtendLayoutInfo`、`CopyAndReSort` 的所有调用；
5. AOT、PGO、serializer、snapshot、runtime stub 与 shared-object 分支。
6. `JSType` 精确 switch、`IsTaggedArray` / `IsCOWArray` / heap visitor、dump 与 snapshot type 编解码。

门禁规则：debug 构建中，任何 Layout mutation 方法接收到 immutable receiver 立即断言；release 构建中仅 owner-aware wrapper 能返回 mutable receiver。机械扫描清单与代码评审逐项对应后才允许开启 flag。构建期增加 `static_assert`，保证 immutable type-state 的对象大小、`LENGTH_OFFSET`、`EXTRA_LENGTH_OFFSET`、`DATA_OFFSET` 与 TaggedArray 完全一致。

### 4.9 Feature Flag 与回滚流程

```text
build flag off -> 不编译 direct-share 分支
build flag on + runtime flag false -> 两个 transition 保留 CopyLayoutInfo
build flag on + runtime flag true  -> 准入后 direct-share + immutable/COW

异常状态 / SharedHeap / owner 不可确定 -> 单次回退现有 copy
```

Runtime flag 启动时读取、进程内不热切换。关闭后新 transition 恢复 copy；已有 immutable Layout 仍是合法只读对象，后续写继续 COW，重启后完全回到基线。

---

## 5. 数据结构设计

### 5.1 Layout Type-State

```cpp
// Mutable 不新增 JSType；CreateLayoutInfo/COW 继续产出 TAGGED_ARRAY。
JSType::TAGGED_ARRAY             // existing mutable state
JSType::IMMUTABLE_LAYOUT_INFO    // append-only immutable state
```

| 属性 | Mutable | Immutable |
|---|---|---|
| TaggedArray 物理格式 | 相同 | 相同 |
| DATA_OFFSET / Length / ExtraLength | 相同 | 相同 |
| 读取 API | 允许 | 允许 |
| 原地 mutation | 允许 | 禁止 |
| owner 写入 | 直接写 | full-physical COW 后写 |
| GC visitor | 相同 | 相同 |

必须同步满足：

```text
JSHClass(IMMUTABLE_LAYOUT_INFO).IsTaggedArray() == true
JSHClass(IMMUTABLE_LAYOUT_INFO).IsCOWArray()    == false
LayoutInfo::Cast(object)                         == valid
visitor range                  == TaggedArray visitor range
sizeof/header/data offsets     == TaggedArray
```

新增 immutable type 不改变现有 JSType 的数值；snapshot/dump 若编码 JSType 数值，必须增加新值的读写分支。flag off 以及所有 COW copy 继续使用现有 TAGGED_ARRAY，因此 flag-off 产物保持原格式。

### 5.2 方案级核心接口

```cpp
bool LayoutInfo::IsMutable() const;
void LayoutInfo::MakeImmutable(JSThread *thread);

JSHandle<LayoutInfo> ObjectFactory::CopyFullPhysicalLayout(
    const JSHandle<LayoutInfo> &source,
    LayoutMutability targetState = LayoutMutability::MUTABLE);

JSHandle<LayoutInfo> JSHClass::EnsureMutableLayout(
    JSThread *thread, const JSHandle<JSHClass> &owner);

JSHandle<LayoutInfo> JSHClass::EnsureMutableLayoutForOwners(
    JSThread *thread,
    const CVector<JSHandle<JSHClass>> &owners,
    const LayoutMutationDescriptor &mutation);
```

接口名称在实现评审中可按工程命名规范落位，但必须保留 owner-aware、full-physical 与批量 family 三项语义。

`IsMutable()` 必须同时检查对象 JSType 和 `Region::ObjectAddressToRange(layout)->InReadOnlySpace()`；`MakeImmutable()` 只允许可写 LocalHeap `TAGGED_ARRAY`，对只读 Region 调用属于实现错误并在 debug 构建断言。

### 5.3 Full-Physical Copy 定义

复制等价条件：

```text
new.GetLength()            == old.GetLength()
new.GetExtraLength()       == old.GetExtraLength()
new.GetPropertiesCapacity()== old.GetPropertiesCapacity()
for i in [0, old.GetLength()): new.rawSlot[i] == old.rawSlot[i]
new.typeState              == TAGGED_ARRAY
```

不得只复制 `NumberOfElements` 可见槽；slack 中的 Hole/default Attr 同样属于物理状态。

### 5.4 统计数据结构

| 计数器 | 含义 |
|---|---|
| `proto_layout_copy_avoided` | `TransitionProto` 省去的 copy 数 |
| `extension_layout_copy_avoided` | `TransitionExtension` 省去的 copy 数 |
| `layout_cow_count` | immutable 到 mutable 的 copy 数 |
| `layout_cow_bytes` | full-physical copy 字节数 |
| `layout_cow_family_count` | 批量 family copy 次数 |
| `layout_cow_owner_fanout` | 每次批量切换 owner 数分布 |
| `layout_immutable_write_reject` | 非零即阻断放行 |
| `layout_share_fallback[]` | SharedHeap、dictionary、owner unknown 等拒绝原因 |

只输出汇总，不在 mutation 热路径逐事件打印。

---

## 6. 兼容性分析

### 6.1 兼容性矩阵

| 路径 | 处理 | 风险 |
|---|---|---|
| `Object.setPrototypeOf` / `__proto__` | proto transition 共享 Layout | 中 |
| `Object.preventExtensions` | extension transition 共享 Layout | 中 |
| `seal` / `freeze` | 后续 Attr 更新必须 COW | 高 |
| property add / defineProperty / delete | 写前 owner COW | 高 |
| TrackType 演化 | family 批量脱离 | 高 |
| representation change | 写前 owner/family COW | 高 |
| PGO dump/update | 置位前 COW | 高 |
| AOT HClass | 保持既有 AOT transition；逐路径准入 | 中 |
| JIT-free | 仍覆盖 AOT/PGO；不把 JIT-free 等同于无 PGO | 中 |
| serializer/snapshot | Layout identity 边变化，字段语义不变 | 低 |
| JSType predicate / heap visitor | 新 type 按 TaggedArray 扫描，不进入普通 COW array 分支 | 高 |
| READ_ONLY_SPACE Layout | 直接视为 immutable；不切 HClass，owner 写入时复制到普通 TAGGED_ARRAY | 高 |
| SharedHeap / Sendable | 排除 | 无新增风险 |
| dictionary mode | 无 Layout 属性写共享，排除 direct-share 准入 | 低 |
| 多 VM / Worker | 每 VM 本地对象，不跨 VM | 低 |
| flag 关闭 | 保留现有 CopyLayoutInfo | 低 |

### 6.2 关键兼容性保证

1. HClass 的 prototype、extensible 与其他 bit fields 保持独立；
2. Layout 的 key、Attr、NumberOfElements、capacity 与全部 slack 槽逐字节保持；
3. compiler 与 stub 继续从同一 `LAYOUT_OFFSET` 读取；
4. `LayoutInfo::Cast`、GC visitor、serializer/snapshot 均识别新 type，继续按 owner HClass 的 Layout Attr 解释字段；
5. SharedHeap 不指向新增 LocalHeap 对象；
6. PGO、TrackType 和 representation 写都经过 owner-aware COW；
7. runtime flag 关闭时两处 copy 及全部现有行为保持。
8. `READ_ONLY_SPACE` Layout 的对象与 HClass 永不被方案 B 修改，写 owner 只获得可写副本。

---

## 7. 性能分析

### 7.1 候选 Layout Shallow 收益

HClass Dump #22 的组 2、3、7 内容与 transition copy 产物形态一致，但终态 dump 不能证明创建路径。以下是“若创建路径标签确认全部来自 B”的紧分配上界：

| 组 | 冗余 Layout | capacity | 候选毛收益 |
|---|---:|---:|---:|
| 2 | 3,568 | 3 | 228,352 B = 223.00 KiB |
| 3 | 1,549 | 4 | 123,920 B = 121.02 KiB |
| 7 | 250 | 4 | 20,000 B = 19.53 KiB |
| 合计 | 5,367 | - | 372,272 B = 363.55 KiB |

该表不是已实现收益。最终归因必须由 `TransitionProto`/`TransitionExtension` 创建路径计数与对象标签证明。

### 7.2 净收益公式

```text
avoided_copy_bytes = sum(copy_avoided_layout_self_size)
cow_bytes          = sum(full_physical_cow_self_size)
type_state_roots   = 新增 Layout HClass 根及常量槽实际 shallow
net_layout_shallow = avoided_copy_bytes - cow_bytes - type_state_roots
```

无 exact-match/weak table 成本。短时峰值需另计 COW 时旧 immutable 与新 mutable 同时存活；Region used/committed、RSS/PSS 不由 shallow 公式推算。

### 7.3 CPU 开销

| 路径 | 变化 |
|---|---|
| proto/extension transition | 省 O(2 * capacity) copy，增加常数级 type-state 判断 |
| Layout 读取 | 零变化 |
| 首次 post-share mutation | 增加 O(2 * capacity) COW |
| 后续同 owner mutation | mutable 后恢复现有成本 |
| TrackType family | 增加 owner 收集/分组；同状态只复制一次 |
| GC | Layout 对象减少；无 weak 表处理；COW 可能产生短期对象 |

### 7.4 放行门槛

- `net_layout_shallow > 0` 且达到 avoided-copy bytes 的至少 30%；
- `layout_cow_bytes / avoided_copy_bytes <= 0.70`；
- proto/extension microbenchmark P50 与 P95 不回退超过 2%；
- 启动 P50 不回退超过 1%，P95 不回退超过 2%；
- property update、TrackType、PGO 热点不回退超过 2%；
- GC pause P50/P95 不回退超过 2%；
- `layout_immutable_write_reject == 0`；
- clean A/B 分列 Layout shallow、Region used/committed、RSS/PSS 和短时峰值。

---

## 8. 风险评估

### 8.1 风险矩阵

| ID | 风险 | 概率 | 影响 | 控制 | 放行证据 |
|---|---|---|---|---|---|
| B-R1 | 漏收口写入口导致跨 HClass 串扰 | 中 | 高 | 全仓机械扫描 + immutable type check | 写调用点清单关闭；非法写计数为 0 |
| B-R2 | TrackType/PGO 单 owner COW 破坏 family 一致性 | 中 | 高 | 批量 owner 分组脱离 | 宽深 transition tree 状态逐节点一致 |
| B-R3 | COW 复制不含 slack/ExtraLength | 低 | 高 | full-physical helper 与逐槽测试 | copy 前后 raw slots 完全一致 |
| B-R4 | SharedHeap 或 AOT 非法准入 | 低 | 高 | LocalHeap fast-property 谓词 | heap verifier 与 AOT 套件通过 |
| B-R5 | COW 频率吞掉收益 | 中 | 中 | avoided/cow byte 计数与门槛 | 净 shallow 达标 |
| B-R6 | 短时双份抬高内存峰值 | 中 | 中 | 峰值与终态分列 | PSS/committed 峰值不超预算 |
| B-R7 | 只删除两处 copy 的不完整实现上线 | 低 | 高 | build 依赖强制绑定 COW/type-state | 缺任一模块时编译失败或 flag 不可见 |
| B-R8 | 终态相同组被错误归因为 B | 中 | 中 | 创建路径标签 | avoided-copy 计数与 dump identity 对齐 |
| B-R9 | Flag 关闭后已有 immutable 对象不可写 | 低 | 中 | COW 基础设施不随 runtime flag 关闭 | flag 切换仅重启；已有对象继续合法 COW |
| B-R10 | 新 JSType 未接入 TaggedArray predicate/visitor | 低 | 高 | append-only type + 全 switch 审计 + static_assert | cast、GC verifier、snapshot type 矩阵通过 |
| B-R11 | 对 READ_ONLY_SPACE Layout 切 HClass 或原地写 | 低 | 高 | Region 判定优先；只读对象直接按 immutable COW | 只读区校验通过，原对象/HClass identity 不变 |

### 8.2 关键风险深入分析

**写入口完整性**：`LayoutInfo` mutation API 之外还可能存在 TaggedArray 基类直写。实现评审必须提交机械扫描结果、逐调用点 owner 获取方式和 SharedHeap 分支处理；仅依赖 debug 断言不足以保证 release 正确性。

**family 一致性**：TrackType 更新通过 transition 子树传播。目标 owner 必须先按旧 Layout identity 与目标状态分组，再共享一个新 mutable copy；逐 owner copy 会放大成本并可能产生状态分裂。

**开关语义**：runtime flag 只控制未来 transition 是否 direct-share，不能关闭 immutable 对象的 COW 支持。COW/type-state 是 build-time 完整依赖，进程内不可撤除。

---

## 9. 测试计划

### 9.1 单元测试

| 用例 | 验证目标 | 通过条件 |
|---|---|---|
| `TransitionProtoSharesLayout` | 省去 proto copy | source/target Layout identity 相同且 HClass proto 不同 |
| `TransitionExtensionSharesLayout` | 省去 extension copy | source/target Layout identity 相同且 extensible 状态不同 |
| `FlagOffCopiesLayout` | 回滚路径 | Layout identity 不同、内容相同 |
| `ImmutableAddPropertyCOW` | AddKey 前脱离 | child 新 Layout，source 视图不变 |
| `ImmutableSetNormalAttrCOW` | Attr 隔离 | 非目标 owner Attr 不变 |
| `ImmutablePGODumpCOW` | PGO 位安全 | 目标 family 一致，其他 owner 不变 |
| `TrackTypeFamilyBatchCOW` | 子树传播 | 同目标状态 owner 共用一份新 Layout |
| `CopyFullPhysicalLayout` | 完整复制 | Length/ExtraLength/raw slots 全同 |
| `ImmutableDirectWriteRejected` | 门禁 | debug 断言，release wrapper 不返回 immutable |
| `LayoutTypeStateTaggedArrayPredicate` | cast 分类 | immutable type 为 IsTaggedArray 且非 IsCOWArray；mutable 为现有 TAGGED_ARRAY |
| `LayoutTypeStateOffsetsAndVisitor` | 物理布局与 GC | offsets 静态断言通过；key/Attr 经全 GC 保活 |
| `LayoutTypeStateSnapshotRoundTrip` | type 编解码 | flag on round-trip 正确；flag off 格式与基线一致 |
| `ReadOnlyLayoutDirectShare` | 只读对象保护 | transition 可共享只读 Layout，原对象与 HClass identity 不变 |
| `ReadOnlyLayoutMutationCOW` | 只读 owner 写入 | 写入落到可写 TAGGED_ARRAY copy，只读原对象不变 |
| `SharedHeapRejected` | 堆域隔离 | 走现有 shared 路径 |
| `DictionaryRejected` | 模式隔离 | 走现有路径 |
| `ExistingTransitionHit` | 缓存路径 | 不新增 freeze/copy/COW |

### 9.2 集成测试

| 场景 | 验证项 |
|---|---|
| proto × add/delete/defineProperty 矩阵 | source/target 属性语义与 descriptor 隔离 |
| preventExtensions/seal/freeze 矩阵 | extensible 与 Attr 变化正确 |
| 宽深 transition tree | family COW、TrackType 与 representation 一致 |
| PGO on/off、AOT on/off | dump/restore/执行结果与基线一致 |
| JIT-free + AOT/PGO | 不遗漏非 JIT 写路径 |
| serializer/snapshot | 表示与反序列化一致，共享边可解释 |
| young/full/concurrent GC | 无 verifier 错误、无悬挂、无非法跨堆边 |
| 多 Worker / 多 VM | 对象只在所属 VM LocalHeap 内共享 |

### 9.3 回归测试

- Test262 prototype、preventExtensions、seal、freeze、descriptor 相关用例 100%；
- `JS_Hclass_Test` 中 transition proto/extension 及新增 COW 用例 100%；
- `JS_LayoutInfo_Test`、GC verifier、AOT/PGO、serializer/snapshot 套件 100%；
- ArkTS/ArkUI 前台、后台、热加载、应用切换与冻结恢复场景无行为差异。

### 9.4 真机验证

1. 同镜像、版本、账号、温度和场景执行 flag off/on clean A/B，每组至少 5 次；
2. 输出 avoided-copy count/bytes、COW count/bytes、family fanout 与 reject 原因；
3. 在 full-GC 后分别统计 distinct Layout、Layout shallow 与 HClass 数；
4. 分列启动 P50/P95、transition microbenchmark、GC pause、Region used/committed、RSS/PSS；
5. 前台与后台快照作为独立终态，不相加；
6. 任何 immutable 直写、属性串扰、AOT/PGO 差异或启动失败均阻断放行。

---

## 10. 评审检查清单

### 10.1 架构合理性

| 检查项 | 结论 |
|---|---|
| 共享关系是否由 transition 直接证明 | 是 |
| 是否引入 exact-match/weak table | 否 |
| HClass 状态是否仍独立 | 是 |
| Layout 读取与物理布局是否不变 | 是 |
| COW 是否为不可拆分依赖 | 是 |

### 10.2 流程正确性

| 检查项 | 结论 |
|---|---|
| 两个 transition 的 flag on/off 流程是否完整 | 是 |
| mutation 是否先取得 owner | 是 |
| full-physical copy 是否包含 slack | 是 |
| family 更新是否批量脱离 | 是 |
| 已有 immutable 对象在 flag off 后是否仍可写 | 是，经 COW |

### 10.3 兼容性与性能

| 检查项 | 结论 |
|---|---|
| SharedHeap/dictionary 是否隔离 | 是 |
| AOT/PGO/JIT-free 是否分别覆盖 | 是 |
| serializer/snapshot 固定解释是否不变 | 是 |
| 候选收益是否标明归因限制 | 是 |
| COW 成本是否从毛收益扣除 | 是 |

### 10.4 风险与回滚

| 检查项 | 结论 |
|---|---|
| 写入口与 JSType switch 清单是否为放行前置 | 是 |
| immutable 直写是否可诊断 | 是 |
| runtime flag 是否默认关闭 | 是 |
| build flag 是否可彻底回滚 direct-share | 是 |

---

## 11. 评审结论

### 11.1 设计结论

本方案可独立实施，但最小交付单元不是“两处删除 `CopyLayoutInfo`”，而是“两处 direct-share + mutable/immutable type-state + full-physical COW + 全部 LocalHeap 写入口 owner 化 + family 批量传播”。任何一项缺失都会使共享 Layout 存在跨 HClass 状态串扰风险。

### 11.2 放行条件

| 维度 | 条件 |
|---|---|
| 正确性 | property/proto/extensible/TrackType/PGO 语义与基线一致 |
| 写安全 | 全仓写入口清单关闭，非法写计数为 0 |
| 内存 | 净 Layout shallow 为正且至少达到 avoided bytes 的 30% |
| 性能 | 启动、transition、mutation、GC 均满足 §7.4 |
| 堆域 | SharedHeap/多 VM verifier 无新增错误 |
| 回滚 | flag off 保留现有 copy；重启后恢复基线 |

### 11.3 工作量与排期

| 工作项 | 设计 | 开发 | 测试 | 小计（人日） |
|---|---:|---:|---:|---:|
| Layout immutable type-state、JSType/visitor 接入与 full-physical copy | 3 | 6 | 5 | 14 |
| mutation 清单与 owner-aware COW 收口 | 3 | 8 | 6 | 17 |
| TrackType/PGO/family 批量脱离 | 3 | 6 | 6 | 15 |
| 两个 transition、Flag 与计数器 | 1 | 3 | 3 | 7 |
| AOT/GC/serializer/真机性能验证 | 1 | 2 | 7 | 10 |
| **合计** | **11** | **25** | **27** | **63 人日** |

两名开发并行排期约 6 周：第 1 周完成 type-state/copy 与写清单；第 2–3 周完成 owner-aware COW；第 3–4 周完成 family/PGO 与 transition；第 5 周完成完整回归；第 6 周完成真机 clean A/B 与评审关闭证据。

### 11.4 归档状态

本文是独立方案设计归档，不代表代码已实现、测试已执行或收益已实现。实施放行以 §11.2 的实测证据为准。

---

## 12. 附录

### 12.1 术语表

| 术语 | 含义 |
|---|---|
| direct-share | transition target 保留 clone 后的源 Layout 指针 |
| type-state | 现有 TAGGED_ARRAY 表示 mutable，新增 immutable Layout HClass；不增加实例字段 |
| read-only Layout | 位于 `READ_ONLY_SPACE` 的既有 Layout；无需新增 JSType，按 immutable 处理 |
| COW | immutable owner 写入前复制完整物理 Layout 并切换 owner |
| full-physical | 包含 Length、ExtraLength、全部 key/Attr 与 slack 槽 |
| family COW | 多个语义上共同变化的 HClass owner 共享一个新 mutable copy |
| avoided-copy | 本应由 `CopyLayoutInfo` 产生、被 direct-share 省去的分配 |

### 12.2 图表索引

| 图表 | 章节 |
|---|---|
| 现有架构图 | 2.1 |
| 目标架构图 | 3.1 |
| TransitionExtension 流程 | 4.1 |
| TransitionProto 流程 | 4.2 |
| 单 owner COW | 4.3 |
| family COW | 4.4 |
| Feature Flag 与回滚 | 4.9 |

### 12.3 冻结源码证据

冻结 revision：`f04900cf951c66c2ea18b2bab5b591d5336c34b9`。

| 事实 | 源码位置 |
|---|---|
| `JSHClass::Clone` 复用原 Layout 指针 | `ecmascript/js_hclass.cpp:227-269` |
| `TransitionExtension` clone 后显式 copy | `ecmascript/js_hclass.cpp:420-446` |
| `TransitionProto` clone 后显式 copy | `ecmascript/js_hclass.cpp:449-481` |
| AddProperty 命中 transition 或 clone 后追加 | `ecmascript/js_hclass.cpp:358-395` |
| AddPropertyToNewHClass 可 copy/re-sort、grow、AddKey | `ecmascript/js_hclass-inl.h:426-454` |
| Layout mutation API 清单 | `ecmascript/layout_info.h:53-75` |
| `SetNormalAttr`、`SetSortedIndex` 原地写 | `ecmascript/layout_info-inl.h:59-110` |
| AddKey 更新 NumberOfElements、key、Attr、sorted index | `ecmascript/layout_info-inl.h:332-359` |
| `UpdateTrackTypeAttr` 与 `SetIsPGODumped` 原地写 | `ecmascript/layout_info-inl.h:292-315` |
| TrackType 沿 transition 子树更新 Layout | `ecmascript/js_hclass.cpp:873-924` |
| PGO dump/update 写 `IsPGODumped` | `ecmascript/layout_info.cpp:191-228`；`ecmascript/js_hclass.cpp:1596-1653` |
| `CopyLayoutInfo` 保持原 Length 并复制数组 | `ecmascript/object_factory.cpp:3518-3523` |
| `LayoutInfo::Cast` 要求 receiver 满足 `IsTaggedArray()` | `ecmascript/layout_info.h:30-45` |
| 现有 `IsTaggedArray` 为 JSType 精确 switch | `ecmascript/js_hclass.h:753-775` |
| `IsCOWArray` 仅识别现有两种数组 COW type | `ecmascript/js_hclass.h:812-817` |
| TaggedArray 的 Length/ExtraLength/DATA_OFFSET 与 variable-length visitor | `ecmascript/tagged_array.h:126-132` |
| compiler/stub 固定读取 HClass Layout 偏移 | `05-源码与数据证据.md:39-49` |
| 全局 `EmptyLayoutInfo` 在 read-only space 初始化 | `ecmascript/global_env_constants.cpp:581-584` |
| Region 提供 `InReadOnlySpace()` 判定 | `ecmascript/mem/region.h:492-495` |

### 12.4 数据证据与复算

HClass Dump #22：

统计口径固定为三层：`HClass owner 数` 只表示引用者数量；`distinct LayoutInfo pointer 数` 表示实际物理 Layout 对象数；`可消除物理副本数 = max(distinct LayoutInfo pointer 数 - 1, 0)`。收益不得使用 `HClass owner 数 - 1` 代替。本表的 owner 与 distinct 恰好相等，不代表两者可在其他组通用替换。

| 组 | HClass owner 数 | distinct LayoutInfo pointer 数 | 可消除物理副本数 | 内容 |
|---|---:|---:|---:|---|
| 2 | 3,569 | 3,569 | 3,568 | function `{length, name, prototype}`，capacity 候选 3 |
| 3 | 1,550 | 1,550 | 1,549 | 组 2 + `identity`，capacity 候选 4 |
| 7 | 251 | 251 | 250 | 组 2 + `__fromPlain__`，capacity 候选 4 |

来源：`LayoutInfo_Identical_Groups.md:2022-2050,2088-2101`。

紧分配复算：

```text
group2 = 3568 * (16 + 16 * 3) = 228352 B
group3 = 1549 * (16 + 16 * 4) = 123920 B
group7 =  250 * (16 + 16 * 4) =  20000 B
total  = 372272 B = 363.546875 KiB
```

终态相同内容不能证明创建来源。实现前后必须给 `TransitionProto` 与 `TransitionExtension` 分配打创建路径标签，以 avoided-copy count/bytes 作为 B 的归因依据。

### 12.5 配套归档

- [01-背景.md](01-背景.md)
- [02-需求.md](02-需求.md)
- [03-方案设计.md](03-方案设计.md)
- [05-源码与数据证据.md](05-源码与数据证据.md)
- [08-方案A-GlobalEnv预建内建Shape-Singleton.md](08-方案A-GlobalEnv预建内建Shape-Singleton.md)
- [10-方案C-Class-Extractor复用Transition-Tree.md](10-方案C-Class-Extractor复用Transition-Tree.md)

### 12.6 更新历史

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-08-28 | v1.0 | 独立方案归档；将 type-state、full-physical COW、全部写入口 owner 化与 family 批量传播纳入不可拆分范围；收益标为需创建路径标签确认的候选上界 |
