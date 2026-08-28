# 方案 C：Class Extractor 复用 HClass Transition Tree 设计评审

> 本文档归档普通 class prototype 的结构 Shape 复用方案。方案以“目标 in-object capacity 的 class-prototype root”逐属性查找或创建 transition，并在继承设置阶段通过 proto transition 分隔不同 internal prototype；不得把基类 prototype 对象自身的 HClass 当作子类属性 Shape 起点。

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.1 |
| 归档日期 | 2026-08-28 |
| 方案范围 | 普通 LocalHeap、fast-mode、interpreter-created class prototype HClass |
| 评审维度 | 架构、流程、数据结构、兼容性、性能、风险、测试、回滚 |
| 实现状态 | 方案归档；未实施，收益须由 extractor 路径标签与 clean A/B 验证 |

---

## 1. 概述

### 1.1 背景

普通 class extractor 当前根据 `nonStaticKeys` 与 `nonStaticProperties` 一次性创建完整 Layout 与 HClass。即使多个 class 的属性序列、Attr、representation 与 in-object capacity 完全相同，每次定义仍产生独立 HClass/Layout。

HClass 本身已提供基于 `(key, property metadata)` 的 property transition 查找与创建能力；`FindTransitions` 还接受 representation 参数，用于校验 AOT transition 的 representation。C 排除 AOT 且固定创建 TAGGED representation，但 extractor 的 `CreatePrototypeHClass` 仍未使用现有 transition tree。直接复用 transition tree 还必须解决两个问题：

1. **in-object capacity**：不同最终属性数不能共用同一 root，否则 HClass object size 与 inlined property capacity 可能偏离现有 extractor 结果；
2. **internal prototype**：现有继承设置对 prototype 对象的 HClass 原地 `SetPrototype`。若多个 class 已共享结构 HClass，该写入会导致不同基类之间串扰。

因此本方案将结构复用与继承域分成两个阶段：

```text
容量 root + property transitions -> structural HClass
structural HClass + parentPrototype -> proto-transition HClass
```

### 1.2 目标

| 目标 | 验收口径 |
|---|---|
| 相同 class prototype 属性序列复用完整 HClass | 相同 capacity、key、Attr、rep、flags 命中相同 structural HClass |
| 不继承基类 own properties | root 只含当前 class 的固定 `constructor` 前缀，不使用 base.prototype 的 HClass/Layout |
| 不同 internal prototype 无串扰 | 继承设置通过 proto transition 切换当前对象 HClass，不原地修改共享 structural HClass |
| 保持 in-object 布局 | final object size、inlined capacity、offset 与现有 extractor 一致 |
| 保持属性值独立 | constructor、方法函数、accessor、home object、lexenv 逐 class 创建 |
| 不依赖方案 B | 当前 `TransitionProto` 的 Layout copy 可保留；B 启用时仅叠加减少该 copy |
| 可回滚 | build/runtime 双开关默认关闭；关闭时执行现有一次性构造与原继承设置 |
| 可观测 | root、property transition、proto transition 命中/创建及拒绝原因可汇总 |

### 1.3 范围

**范围内**：

- `ClassHelper::DefineClassFromExtractor` 中普通 LocalHeap class prototype；
- 仅 `ClassHelper::DefineClassFromExtractor` 的普通 interpreter-created prototype 准入；凡进入 `DefineClassWithIHClass` 的完整或部分 AOT 路径均排除；
- VM 配置必须保证整个生命周期不启用 runtime/JIT PGO；
- `2 <= nonStaticKeys.length <= MAX_FAST_PROPS_CAPACITY`；
- 固定 constructor 前缀、且由方案级 provenance 明确证明全部 non-static key 来自非 computed literal string 的普通方法/命名方法/accessor；
- capacity root registry、property transition tree、proto transition 隔离；
- Feature Flag、统计、GC、测试与回滚。

**范围外**：

- constructor function 的 static Shape；
- 长度 1 的 `{constructor}` Shape，该 case 由方案 A 或现有路径处理；
- dictionary mode；
- Sendable / SharedHeap class；
- AOT 已提供 prototype/HClass；
- PGO profiler enabled；
- class elements 路径的首阶段放行；
- symbol method 与 computed property name；
- N-API `napi_define_class`；
- 任意普通 JSObject Shape；
- exact-match Layout table、跨 VM/Realm/进程共享；
- 基类 prototype 对象 HClass 的属性链复用。

---

## 2. 现有架构分析

### 2.1 现有架构图

```text
ClassInfoExtractor
  +-- nonStaticKeys[]
  `-- nonStaticProperties[]
             |
             v
CreatePrototypeHClass
  +-- CreateLayoutInfo(length, KEEP)
  +-- for each key: build Attr + AddKey
  +-- NewEcmaHClass(JSObject, length)
  +-- SetLayout / NumberOfProps
  `-- SetClassPrototype / SetIsPrototype
             |
             v
NewOldSpaceJSObject(prototypeHClass)
  -> 写每个 inlined property value
  -> DefinePropertyOrThrow(constructor)
  -> RuntimeSetClassInheritanceRelationship
       `-- prototypeHClass.SetPrototype(parentPrototype)  [原地写]
```

### 2.2 现有属性构造规则

普通 prototype fast path 的 Attr 规则：

| 字段 | 规则 |
|---|---|
| writable | true |
| enumerable | false |
| configurable | true |
| accessor | `properties[index].IsAccessor()` |
| inlined | true |
| representation | TAGGED |
| offset | extractor index |
| sorted index | `LayoutInfo::AddKey` 计算 |

constructor 固定处于 index 0。方法值和 accessor 对象不进入 transition key；runtime transition 字典以 key 与 property metadata 匹配。C 的 representation 固定为 TAGGED，作为 child 创建不变量与命中后 debug 断言；不把它表述为字典键。

冻结 `ClassInfoExtractor` 只保留求值后的 `nonStaticKeys`/`nonStaticProperties`，其 BitField 只有 `NonStaticWithElements` 与 `StaticWithElements`。`NonStaticWithElements` 仅表示字符串 key 可转换为 element index，不能证明 key 是否来自 computed name。因此 runtime 不能从已归一化的 string identity 反推 literal/computed 来源。首阶段新增版本化 abc 可选元数据 `ClassLiteralKeyProvenance`，由前端按 class-literal EntityId 产生，loader 写入 `JSPandaFile` native side table；取值为 `UNKNOWN`、`LITERAL_ONLY`、`HAS_DYNAMIC_KEY`。只有 `LITERAL_ONLY` 准入，旧格式、缺失记录、未知 producer 和 `HAS_DYNAMIC_KEY` 均整类回退。该元数据、side table 与读取接口均为方案级待实现，不是冻结源码已有能力；不修改 `ClassLiteral`、`ClassInfoExtractor` 或其他 GC 对象布局。

### 2.3 现有架构问题

| 问题 | 影响 |
|---|---|
| extractor 每次完整构造 HClass/Layout | 相同 Shape 不能复用已有 transition |
| 直接从 base.prototype 的 HClass 生长 | 会把基类自有属性错误带入子类 own Shape |
| transition root 未区分 capacity | 可能改变 object size、inlined property 数与 offset 解释 |
| 继承设置原地写 HClass prototype | 共享 structural HClass 后会跨 class 串扰 |
| AOT/Sendable/dictionary 语义不同 | 不能共用普通 LocalHeap 入口 |
| extractor 不保留 property-name 来源 | 无法仅靠运行时 string key 排除 computed name |
| 终态相同组无创建路径标签 | 无法仅凭 dump 证明来自 class extractor |

---

## 3. 目标架构设计

### 3.1 目标架构图

```text
                         per-VM ClassPrototypeShapeRootRegistry
                         key = target in-object capacity
                                      |
                                      v
                         root(inlined capacity=N)
                         Shape: {constructor}
                         Props: 1, Layout capacity: 1
                                      |
              +-----------------------+-----------------------+
              | property transition(key, metadata)           |
              v                                               v
       {constructor, m1}                              {constructor, accessor1}
              |
              v
       structural final HClass (proto 尚未分域)
              |
              | allocate 独立 prototype object + 独立值
              v
       Resolve parentPrototype by existing class semantics
              |
              v
       TransitionProto(structural HClass, parentPrototype)
              |
              +-- same shape + same parentPrototype: 命中同一 final HClass
              `-- different parentPrototype: 独立 final HClass
                                      |
                                      v
                         当前 prototype object 切换 HClass
```

### 3.2 架构设计原则

| 原则 | 约束 |
|---|---|
| 容量先分域 | root key 为最终 in-object capacity，不在一棵树混用不同 object size |
| 属性 transition 复用 | 每一步使用现有 key + metadata 匹配；TAGGED representation 固定并校验；miss 时构建私有 prefix Layout |
| prototype 后分域 | internal prototype 使用 proto transition，不直接改共享 structural HClass |
| base Shape 不参与 | 只使用 `base.prototype` 对象 identity 作为 internal prototype，不继承其 Layout |
| 值与 Shape 分离 | 仅复用 HClass/Layout；所有函数与值逐 class 创建 |
| 现有语义顺序 | base 校验、prototype 读取、异常时点须与现有 class 定义顺序一致 |
| 读取零改动 | HClass/Layout 物理结构、property offset 与 object slot 不变 |
| 弱 transition 生命周期 | root registry 强持有容量 root；property/proto child 沿用现有 transition 生命周期 |
| 失败回退 | 任一边界不满足，整次 class 定义走现有路径 |

### 3.3 组件关系

| 组件 | 职责 | 变更 |
|---|---|---|
| GlobalEnv / GlobalEnvConstants | 持有 per-VM capacity root registry | 增加一个 GC 可见根 |
| ClassPrototypeShapeRootRegistry | 按 target capacity 返回/创建 `{constructor}` root | 方案级新增组件 |
| 前端 / abc writer | 产生按 class-literal EntityId 索引的三态来源摘要 | 方案级新增可选 metadata 记录 |
| JSPandaFile / loader | 解析记录到 native side table；缺失时返回 `UNKNOWN` | 方案级新增非 GC 数据与 getter |
| ClassInfoExtractor | 接收 provenance、构造精确 Attr，逐属性查找/创建 transition | 增加 fail-closed 参数与准入分支 |
| JSHClass | 复用 `FindTransitions`、`AddTransitions`、`TransitionProto` | 增加 extractor 专用 persistent transition builder |
| `RuntimeCreateClassWithBuffer` / `RuntimeSetClassInheritanceRelationship` | 以当前调用栈中的显式 fast-path 结果选择 proto transition 并切换 HClass | 增加内部参数；禁止按 HClass identity 猜测 |
| ObjectFactory | 创建 capacity root 与 prototype 对象 | 增加 root factory helper |
| JSOptions / FeatureConfig | build/runtime 双开关 | 默认关闭 |
| 统计模块 | root/transition/proto 命中与创建 | 汇总输出 |

---

## 4. 流程设计

### 4.1 准入流程

```text
CreatePrototypeHClass(keys, properties, extractorContext)
  |
  +-- flag 关闭 ------------------------------> 现有一次性构造
  +-- Sendable / SharedHeap ------------------> 现有 sendable 路径
  +-- AOT supplied prototype/HClass ----------> 现有 AOT 路径
  +-- VM 不满足 lifetime PGO-off 约束 ---------> 现有 extractor 路径
  +-- withElements ---------------------------> 首阶段现有路径
  +-- provenance 缺失或非 literal-only -------> 现有 extractor 路径
  +-- 任一 key 为 symbol ----------------------> 现有 extractor 路径
  +-- length < 2 或 length > MAX_FAST --------> 方案 A/现有/dictionary 路径
  +-- key[0] != canonical constructor --------> 现有路径
  +-- 任一 key 非 PropertyKey ----------------> 保持现有异常/断言语义
  `-- 全部满足
        -> GetOrCreateRoot(length)
        -> BuildPrototypeShapeByTransitions(root, keys, properties)
        -> 返回 structural HClass
```

准入按整次 class 定义决定；中途不允许在已创建半棵 transition 后切到一次性 HClass 并混合两种 offset 规则。provenance 必须在调用 `GetOrCreateRoot` 之前验证；旧 abc、热补丁或 translator 未提供可信摘要时按“存在 computed name”处理并回退。

### 4.2 Capacity Root 创建流程

```text
GetOrCreateRoot(N)
  |
  +-- registry[N] 命中 -> 返回 root
  |
  `-- miss
        +-- 创建 HClass: JS_OBJECT, inlined capacity N
        +-- 复用现有 canonical {constructor} Layout
        |     capacity = 1, NumberOfElements = 1
        +-- NumberOfProps = 1
        +-- SetClassPrototype(true)
        +-- SetIsPrototype(true)
        +-- internal prototype 保持结构阶段默认值
        +-- publish 到 registry[N]
        `-- 返回 root
```

root 是 transition 父节点，不分配可见 JSObject。HClass 的 inlined capacity 为 N，但 Layout 复用现有 capacity=1 的 canonical `{constructor}` Layout；因此 root 不强引用任何动态方法 key。registry 使用 GC 管理的 capacity-indexed 稀疏容器；它不是按 Layout 内容匹配的 exact-match table。首阶段仅允许 `N` 为实际 class prototype 长度，禁止预建 `MAX_FAST_PROPS_CAPACITY + 1` 个 HClass。

### 4.3 Property Transition 构建流程

```text
current = root(N)
for index in [1, N):
  key  = keys[index]
  attr = BuildPrototypeAttr(properties[index], index)
  rep  = TAGGED

  next = current.FindTransitions(key, attr.metadata, rep)
  if next exists:
      assert next.inlinedCapacity == N
      assert next.NumberOfProps == index + 1
      assert next.Layout[index] full-attr == attr
      current = next
  else:
      current = CreatePersistentClassPrototypeTransition(
          parent=current,
          key=key,
          attr=attr,
          representation=rep,
          targetInlinedCapacity=N,
          targetLayoutCapacity=N)
return current
```

`FindTransitions` 的 runtime transition dictionary 以 key 与 property metadata 匹配；representation 参数只会在 AOT HClass 上进一步校验，而 C 已排除 AOT。命中后仍需 debug 全字段断言，包括 TAGGED representation、offset、inlined、accessor、sorted index、flags、object size 与 capacity；release 依赖创建侧不变量。

`CreatePersistentClassPrototypeTransition` 不得直接调用通用 `AddPropertyToNewHClass` 后依赖其 grow 分支。它必须按以下顺序执行：

```text
child = Clone(parent, specificInlinedProps=true, N)
childLayout = CopyAndReSort(parent.Layout,
                            end=parent.NumberOfProps,
                            capacity=N)
child.SetLayout(childLayout)
AddPropertyToNewHClassWithoutTransition(child, key, attr)
AddTransitions(parent, child, key, attr)
return child
```

每条新边拥有自己的固定最终 capacity=N Layout，parent Layout 不被原地追加。root 的自身 Layout 只强引用 canonical `constructor`；transition dictionary 对 child 使用 weak value，但 key 槽是强引用，dead child 的 key 直到后续 grow/rehash 才被过滤。首阶段因此只接收 provenance 已证明的 literal string key，不接收 symbol 或 computed key。该 helper 与 provenance 接口均为方案级待实现能力；`AddTransitions` 当前为 JSHClass 私有方法，实现时在 JSHClass 内封装，不从 extractor 绕过可见性。

### 4.4 Prototype 对象和值写入流程

```text
structuralHClass = BuildPrototypeShapeByTransitions(...)
prototype = NewOldSpaceJSObject(structuralHClass)
constructor = NewJSFunctionByHClass(...)
nonStaticProperties[0] = constructor

for index in [0, N):
  FunctionTemplate -> 创建独立 JSFunction
                      设置本 class 的 homeObject 与 lexenv
  其他值            -> 原值
  prototype.slot[index] = 独立值

DefinePropertyOrThrow(prototype, "constructor", descriptor)
constructor.SetHomeObject(prototype)
constructor.SetProtoOrHClass(prototype)
```

方法值、accessor、home object、lexical environment、constructor 和 prototype object 均不共享。共享 HClass 不改变 slot 写入顺序与 offset。

### 4.5 Internal Prototype 分域流程

现有 class 继承语义解析 `parentPrototype`：

```text
base is Hole  -> Object.prototype
base is Null  -> null
base ctor     -> Get(base, "prototype"); 必须是 object 或 null
```

准入 case 的 prototype HClass 处理：

```text
structural = prototype.GetJSHClass()
final = structural.FindProtoTransition(parentPrototype)
if miss:
    final = TransitionProto(structural, parentPrototype, isChangeProto=false)
prototype.SynchronizedTransitionClass(final)

assert final.prototype == parentPrototype
```

是否执行该分支必须由本次 `DefineClassFromExtractor` 返回的显式 `prototypeShapeShared` 结果决定。`RuntimeCreateClassWithBuffer` 将该栈上布尔值传给紧随其后的 `RuntimeSetClassInheritanceRelationship`；AOT、interface、clone、`RuntimeResolveClass` 和拒绝路径固定传 `false`。不得通过 `prototype.GetJSHClass() == registry root/child` 或 HClass flags 猜测，因为普通对象可能经其他 transition 到达相同字段状态，且 weak child 重建会改变 identity。

不得执行：

```text
structural->SetPrototype(parentPrototype);  // 禁止：会修改共享 structural HClass
```

constructor HClass 的 `__proto__` 仍按既有路径设置；本方案只替换 `clsPrototype->GetClass()->SetPrototype(parentPrototype)` 这一项。prototype 对象切换到 final HClass 后，既有 `ObjectOperator::UpdateDetectorOnSetPrototype`、AOT constructor/prototype `EnableProtoChangeMarker` 与后续 profile 处理继续执行并观察 final HClass。

### 4.6 语义顺序与异常流程

- `base` 是否为 constructor、`base.prototype` 的属性读取及异常传播顺序必须与现有 `RuntimeSetClassInheritanceRelationship` 一致；
- 按 base 设置 constructor `FunctionKind`、constructor HClass `__proto__`、detector 更新、AOT proto-marker 与后续 profile 处理的顺序保持；
- 不允许为了选择 root 在 extractor 早期提前触发 `Get(base, "prototype")`；
- structural HClass 可在现有时点创建，但 proto transition 只在既有继承关系设置时点执行；
- `base.prototype` getter 抛异常时，class 定义按现有机制中止，未暴露的 prototype/constructor 由 GC 回收；
- proto transition 或 HClass 切换不得新增可观察 JavaScript 调用；
- Proxy base 与自定义 `prototype` getter 的调用次数、顺序和异常保持不变。

### 4.7 AOT 与 `DefineClassWithIHClass`

```text
ClassHelper::DefineClassFromExtractor
  -> 可进入 C 的 interpreter-created prototype 准入

DefineClassWithIHClass: prototypeOrHClassVal is JSHClass
  -> 使用 AOT HClass 与 proto 对象；不重建 property transition tree

DefineClassWithIHClass: prototypeOrHClassVal is prototype object
  -> 使用该对象；不重建 property transition tree

DefineClassWithIHClass: partial AOT information 缺失后回退 CreatePrototypeHClass
  -> 仍按 AOT-family 现有路径处理；不进入 C
```

constructor HClass 的 AOT/interpreter 分支不在本方案内。AOT supplied prototype 的 correction、proto marker 与 profile 行为保持现状；不能仅凭内部最终调用了 `CreatePrototypeHClass` 就把 partial-AOT fallback 误纳入 C。

### 4.8 PGO、TrackType 与 HClass 状态

C 只在 VM 配置保证整个生命周期不启用 runtime/JIT PGO 时准入。`ProfileDefineClass` 会用 constructor method id 给 constructor、instance 与 prototype root HClass 写 class-specific ProfileType；让不同 class literal 共用 property root/final HClass 会造成 ProfileType identity 冲突。冻结实现支持 JIT post-fork 打开 PGO，已共享的 root 无法在 late-enable 时恢复 class-specific identity，因此仅在每次 class 创建时检查当前状态不充分：C 必须从 VM 初始化起关闭，或在 C 已开启时拒绝 late PGO/JIT-PGO enable。JIT-free 配置若仍启用 PGO，同样拒绝；JIT-free 不等同于 PGO-free。

PGO-off 时，C 复用的是完整 final HClass，而不是让多个语义不同的 HClass 指向同一 Layout：

- 同一 `(capacity, property sequence, Attr, representation, parentPrototype)` 的对象共享 HClass，其 TrackType/PGO state 按现有 HClass-level 语义共同演化；
- 不同 parentPrototype 通过 proto transition 获得不同 HClass；
- 不同 accessor/data metadata 进入不同 property transition；C 的 representation 始终为 TAGGED；
- 若状态写需要形成新的 HClass transition，沿用现有 HClass 演化；
- C 不要求方案 B 的 Layout COW；当前 `TransitionProto` 的 Layout copy 可保留；
- 若 B 同时启用，proto-transition HClass 可共享 Layout，但必须由 B 的 immutable/COW 约束保证。

### 4.9 Root Registry 生命周期与 GC

- registry 是 per-VM GC root，不跨 VM/Realm/进程；
- root 按实际命中的 capacity 懒创建；
- root 强存活到 VM 销毁，property/proto transition child 沿用现有 weak transition 表示与 GC 处理；
- PGO-off 下不额外写 `JSHClass::Parent` 强链；中间 prefix 或 structural HClass 被 GC 后，后续定义允许 transition miss 并重建，属于缓存命中率变化，不影响对象语义；
- transition dictionary 的 value/heap metadata 为 weak ref，key 槽为强引用；dead value 在后续 grow/rehash 时被过滤，需统计 dead entry、rehash 与 retained key；
- registry 不保存 key sequence、Layout hash 或用户属性值；
- root 仅引用 capacity=1 的 canonical constructor Layout；每条新 property edge 使用私有 capacity=N Layout，parent 不原地写；
- VM 销毁时 registry、root 与仍存活的 transition 子树按现有 GC 生命周期释放。

### 4.10 Feature Flag 与回滚流程

```text
build flag off -> 不编译 root registry 与 extractor transition 分支
build flag on + runtime flag false
  -> CreatePrototypeHClass 一次性创建
  -> RuntimeSetClassInheritanceRelationship 原地 SetPrototype
build flag on + runtime flag true
  -> 准入 case 使用 structural transition tree
  -> DefineClassFromExtractor 返回 prototypeShapeShared=true
  -> 当前 RuntimeCreateClassWithBuffer 调用把该值传给继承设置
  -> 继承设置使用 proto transition + object HClass switch
拒绝 case -> 从创建开始完整执行现有路径
```

runtime flag 在进程启动读取，不热切换。关闭并重启后恢复现有 HClass/Layout identity；对象物理格式无变化，不需要迁移或 snapshot 版本升级。

---

## 5. 数据结构设计

### 5.1 ClassPrototypeShapeRootRegistry

```cpp
// 方案级接口；实现命名按工程规范落位。
class ClassPrototypeShapeRootRegistry final {
public:
    JSHandle<JSHClass> GetOrCreate(JSThread *thread, uint32_t inlinedCapacity);
};
```

物理表示固定为 GC 管理的稀疏 TaggedArray：

```text
Registry
  [0] capacity_0_or_hole
  [1] root_hclass_0
  [2] capacity_1_or_hole
  [3] root_hclass_1
  ...
```

| 字段 | 约束 |
|---|---|
| capacity | `2..MAX_FAST_PROPS_CAPACITY`，仅按实际命中创建 |
| root | JS_OBJECT、NumberOfProps=1、inlined capacity=capacity |
| root Layout | 复用 capacity=1 的 canonical `{constructor}` Layout |
| flags | class prototype=true、prototype=true、dictionary=false、shared=false |
| internal prototype | structural 默认值；不得写入用户 parentPrototype |

registry 仅按整数 capacity 查 root，不按 Layout 内容查对象。若实际容量种类超过预设稀疏容器阈值，扩容容器但不预建 root。

### 5.2 方案级核心接口

```cpp
JSHandle<JSHClass> ObjectFactory::CreateClassPrototypeShapeRoot(
    uint32_t inlinedCapacity);

JSHandle<JSHClass> ClassInfoExtractor::BuildPrototypeHClassByTransitions(
    JSThread *thread,
    const JSHandle<TaggedArray> &keys,
    const JSHandle<TaggedArray> &properties);

PropertyAttributes ClassInfoExtractor::BuildPrototypePropertyAttr(
    JSThread *thread, JSTaggedValue property, uint32_t index);

// 方案级 provenance；冻结 JSPandaFile/ClassInfoExtractor 当前没有该信息。
enum class ClassLiteralKeyProvenance : uint8_t {
    UNKNOWN,
    LITERAL_ONLY,
    HAS_DYNAMIC_KEY,
};

ClassLiteralKeyProvenance JSPandaFile::GetClassLiteralKeyProvenance(
    EntityId literalId) const;

JSHandle<JSFunction> ClassHelper::DefineClassFromExtractor(
    ...,
    ClassLiteralKeyProvenance provenance,
    bool &prototypeShapeShared);

JSHandle<JSHClass> JSHClass::CreatePersistentClassPrototypeTransition(
    JSThread *thread,
    const JSHandle<JSHClass> &parent,
    const JSHandle<JSTaggedValue> &key,
    const PropertyAttributes &attr,
    uint32_t targetInlinedCapacity);

JSHandle<JSHClass> JSHClass::GetOrCreateClassPrototypeProtoTransition(
    JSThread *thread,
    const JSHandle<JSHClass> &structural,
    const JSHandle<JSTaggedValue> &parentPrototype);

JSTaggedValue RuntimeStubs::RuntimeSetClassInheritanceRelationship(
    JSThread *thread,
    const JSHandle<JSTaggedValue> &ctor,
    const JSHandle<JSTaggedValue> &base,
    ClassKind kind,
    bool prototypeShapeShared);
```

`BuildPrototypePropertyAttr` 必须与现有 `CreatePrototypeHClass` 共用一个实现，防止两条路径的 Attr 规则漂移。abc metadata 是版本化可选记录，不改变 class literal 数组 trailer；loader 对没有该记录的旧 abc 返回 `UNKNOWN`，热补丁沿用各自 JSPandaFile side table，AOT snapshot 不复制或合成 provenance。`RuntimeCreateClassWithBuffer` 的 `literalId` 是常量池索引，必须先通过当前 unshared constant pool 的 `GetEntityId(literalId)` 取得 class-literal EntityId，再查询当前 `JSPandaFile` side table并传入 extractor；禁止把常量池索引直接作为 side-table key。`prototypeShapeShared` 仅存在于当前 C++ 调用栈，不写入 JSFunction/JSHClass，不改变 GC 对象布局或 snapshot schema。

### 5.3 Transition Identity

结构 HClass identity：

```text
(capacity,
 ordered [key, propertyMetadata] sequence,
 fixed representation = TAGGED,
 JSType,
 objectSize,
 classPrototype/prototype flags,
 elementsKind)
```

final HClass identity：

```text
(structural HClass identity, parentPrototype identity)
```

属性值、FunctionTemplate、Method、homeObject 与 lexenv 不进入 Shape identity。

### 5.4 统计数据结构

| 计数器 | 含义 |
|---|---|
| `class_shape_root_hit[N]` | capacity root 命中数 |
| `class_shape_root_create[N]` | capacity root 创建数 |
| `class_property_transition_hit` | 属性 transition 命中边数 |
| `class_property_transition_create` | 属性 transition 新建边数 |
| `class_structural_hclass_reuse` | 完整 structural HClass 命中数 |
| `class_proto_transition_hit` | `(shape, parentPrototype)` 命中数 |
| `class_proto_transition_create` | proto-domain HClass 创建数 |
| `class_shape_fallback[]` | elements/AOT/dictionary/flag 等拒绝数 |
| `class_shape_fallback_provenance` | 缺失、旧格式或包含 computed non-static key 的拒绝数 |
| `class_shape_fallback_pgo` | VM 不满足 lifetime PGO-off 约束的拒绝数 |
| `class_shape_late_pgo_enable_reject` | C 已开启后拒绝 late PGO/JIT-PGO 的次数 |
| `class_shape_proto_inplace_violation` | 非零即阻断放行 |
| `class_transition_dead_entry_seen` | full GC 后 weak value 已清空的 entry 数 |
| `class_transition_rehash` | C root/child transition dictionary rehash 次数 |
| `class_transition_retained_key_after_rehash` | rehash 后仍无 live weak value 却保留 key 的 entry 数；必须为 0 |

只输出汇总；不得在 class method 循环或 transition 查找中逐事件打印。

---

## 6. 兼容性分析

### 6.1 兼容性矩阵

| 路径 | 处理 | 风险 |
|---|---|---|
| 普通 class methods | key/metadata transition；TAGGED rep 固定 | 中 |
| getter/setter | accessor metadata 分支 | 中 |
| computed property name | provenance 非 literal-only，整次执行现有 extractor 路径；缺失 provenance 同样回退 | 无新增风险 |
| symbol method | 首阶段排除，避免常驻 root dictionary 保留 symbol key | 无新增风险 |
| `class B extends A` | parentPrototype proto transition | 高 |
| `class B extends null` | null proto transition | 中 |
| base Proxy / prototype getter | 调用时点和次数保持 | 高 |
| static methods/fields | constructor HClass 仍走现有路径 | 无新增风险 |
| class elements | 首阶段排除 | 无新增风险 |
| dictionary prototype | 排除 | 无新增风险 |
| AOT supplied HClass/prototype | 排除 | 无新增风险 |
| lifetime PGO-off | 可执行 C 准入 | 中 |
| runtime/JIT PGO 可能启用 | VM 初始化时禁用 C，执行现有 extractor 路径 | 低 |
| JIT-free | 仅 PGO 同时关闭时可准入；不等同于 AOT-free 或 PGO-free | 中 |
| Sendable/SharedHeap | 排除 | 无新增风险 |
| multi-context / Realm | per-VM registry；parentPrototype identity 分域 | 中 |
| serializer/snapshot | HClass identity 边变化，字段解释不变 | 低 |
| flag 关闭 | 现有一次性构造与继承设置 | 低 |

### 6.2 关键兼容性保证

1. 不从 base.prototype 的 HClass 继承任何 own Layout；
2. root 与 final HClass 的 inlined capacity、object size、offset 与 extractor `length` 一致；
3. key 与 property metadata 参与 runtime transition identity；representation 在 C 中固定为 TAGGED 并在命中后校验；
4. 不同 parentPrototype 不共享 final HClass；
5. 继承设置不对 shared structural HClass 原地写；
6. prototype 对象和所有属性值逐 class 独立；
7. AOT、Sendable、dictionary、elements、computed 与 provenance 缺失 case 保持现有路径；
8. base getter 的时序、异常和调用次数不改变；
9. constructor FunctionKind/`__proto__`、detector、AOT proto-marker 与 profile 处理保持；
10. proto-transition 分流只使用本次调用栈上的显式结果，不根据 HClass identity 或 flags 推断。

---

## 7. 性能分析

### 7.1 候选 Layout Shallow 收益

HClass Dump #22 中组 5、6 以 `constructor` 为首属性，符合 class prototype 候选形态。若创建路径标签确认来自普通 class extractor，紧分配毛上界为：

| 组 | 冗余 Layout | capacity | 候选毛收益 |
|---|---:|---:|---:|
| 5 | 821 | 3 | 52,544 B = 51.31 KiB |
| 6 | 760 | 2 | 36,480 B = 35.63 KiB |
| 合计 | 1,581 | - | 89,024 B = 86.94 KiB |

组 8 的 Shape 为 `{init, $super, high, low}`，不含固定 `constructor` 前缀，不计入本方案。

### 7.2 HClass 与净收益公式

C 同时复用完整 HClass；净收益必须扣除 capacity root、property prefix 节点与 parentPrototype 分域节点：

```text
avoided_final_layout = sum(extractor final Layouts eliminated)
avoided_final_hclass = sum(extractor final HClasses eliminated)
root_cost            = sum(capacity roots: HClass + registry slots)
prefix_cost          = sum(unique property-prefix HClass + fixed capacity-N Layout)
proto_domain_cost    = sum(unique (structural shape, parentPrototype) HClass
                           + TransitionProto Layout copy)
net_shallow          = avoided_final_layout + avoided_final_hclass
                       - root_cost - prefix_cost - proto_domain_cost
```

若方案 B 同时开启，`TransitionProto` 的 Layout copy 可进一步下降，但 C 的独立收益必须在 B 关闭时也为正。

### 7.3 CPU 开销

| 路径 | 变化 |
|---|---|
| 首次新 Shape | 增加逐属性 transition 查找与 prefix HClass；替代一次性 Layout 构造 |
| 重复 Shape | 命中已有 property transitions，省 HClass/Layout 分配和 AddKey |
| 继承设置 | 增加 proto transition 查找；命中时省原地状态初始化，miss 时创建分域 HClass |
| 属性读取/写入 | 零变化 |
| compiler/stub | 零变化 |
| GC | HClass/Layout 数下降；root 常驻；child 使用现有 transition 生命周期 |

### 7.4 放行门槛

- C 独立运行时 `net_shallow > 0`；
- 候选组中 extractor 路径归因率必须由标签报告，不设推断值；
- class definition 重复 Shape microbenchmark P50 至少改善 3%，P95 不回退；
- 首次唯一 Shape microbenchmark 不回退超过 2%；
- 应用冷启动 P50 不回退超过 1%，P95 不回退超过 2%；
- registry + root + prefix + proto-domain shallow 全部纳入净值；
- `class_shape_proto_inplace_violation == 0`；
- full GC 触发后 `class_transition_retained_key_after_rehash == 0`，dead-entry/rehash 计数与 dump 抽样一致；
- Region used/committed、RSS/PSS 与 shallow 分列，不从对象数推算物理收益。

---

## 8. 风险评估

### 8.1 风险矩阵

| ID | 风险 | 概率 | 影响 | 控制 | 放行证据 |
|---|---|---|---|---|---|
| C-R1 | 直接从 base HClass 生长带入基类 own properties | 低 | 高 | capacity root 与 base Shape 完全隔离 | 子类 ownKeys/descriptor 与基线一致 |
| C-R2 | 原地 SetPrototype 污染共享 structural HClass | 中 | 高 | proto transition + object HClass switch | 不同 base/null/Realm 压测无串扰；violation=0 |
| C-R3 | capacity 不同却命中同一树 | 低 | 高 | registry 按 capacity 分域 + debug 断言 | object size/slot offset 全矩阵一致 |
| C-R4 | accessor/data 或 Attr 元数据误命中 | 低 | 高 | 共用 Attr builder；metadata 参与字典键；TAGGED rep 固定并在命中后断言 | descriptor/accessor 矩阵通过 |
| C-R5 | 提前读取 base.prototype 改变副作用与异常时序 | 中 | 高 | 保持现有 RuntimeSet 时点 | Proxy/getter 调用序列与基线一致 |
| C-R6 | root 常驻与每边私有 prefix Layout 成本吞掉收益 | 中 | 中 | lazy sparse registry + 净收益公式 | C 独立 net shallow 为正 |
| C-R7 | dead weak child 的 transition key 被强槽保留到 rehash | 中 | 中 | 排除 symbol/computed key；统计 dead entry/rehash/retained key | full-GC + rehash 后 key 保留符合基线 |
| C-R8 | AOT/PGO/Sendable/elements 错误准入 | 低 | 高 | VM-lifetime PGO 互斥 + 整次创建前封闭谓词 | PGO-capable VM 的 C hit=0；late-enable 被拒绝 |
| C-R9 | 组 8 被错误计入收益 | 中 | 中 | 必须有 constructor 前缀和 extractor 标签 | 收益报告不含组 8 |
| C-R10 | C 对 B 形成隐式依赖 | 低 | 中 | 保留当前 proto Layout copy；单独开关测试 | B off/C on 全测试与净收益通过 |
| C-R11 | weak prefix/structural 节点被 GC 后缓存链断开 | 中 | 中 | 沿用弱 transition；允许重建；不增加强 parent 链 | GC 前后命中率、重建数与净收益达标 |
| C-R12 | extractor 从已求值 string 误判 computed 来源 | 中 | 高 | translator provenance fail-closed；旧/缺失摘要回退 | computed/symbol/旧 abc 的 C hit=0 |
| C-R13 | 继承入口把普通 HClass 误判为 C structural HClass | 低 | 高 | 栈上 `prototypeShapeShared` 显式传递；其他调用点固定 false | 所有 `RuntimeSetClassInheritanceRelationship` 调用点分流测试通过 |

### 8.2 关键风险深入分析

**继承域隔离**：共享 structural HClass 不能执行原地 `SetPrototype`。实现必须让当前 prototype 对象切换到 `(structural, parentPrototype)` 对应 HClass；同一 structural 下不同 parentPrototype 必须得到不同 identity。

**容量根**：HClass object size 与 inlined property 数影响对象分配和 slot 偏移。root 以最终 `length` 分域，并在每个 transition hit 上断言 capacity 与 object size；不能依赖 Layout grow 策略间接推导。

**时序**：基类可能为 Proxy，`base.prototype` 读取可执行用户代码并抛异常。方案只替换 HClass 设置动作，不提前读取或缓存该值。

**弱缓存生命周期**：PGO-off 的 `AddTransitions`/`AddProtoTransitions` 不设置 child `Parent`，transition value 是 weak ref。final proto-domain HClass 存活不保证 property prefix/structural 节点存活。C 保持该语义，不建立强 parent 链；full GC 后允许 cache miss 和等价路径重建。dictionary key 是强槽，dead child key 在后续 grow/rehash 时才被过滤，因此首阶段排除 symbol/computed key，收益与 retained-key 门槛覆盖 GC 前后两个稳态窗口。

**provenance 与分流**：冻结 extractor 没有 computed 来源位，冻结继承入口也没有 C 命中参数。方案以 JSPandaFile native side table 提供三态来源摘要并 fail-closed；fast-path 结果只沿当前 `RuntimeCreateClassWithBuffer` 栈传递。任一 producer/caller 未适配时只能走现有路径，不能通过运行时 key 或 HClass identity 猜测。

---

## 9. 测试计划

### 9.1 单元测试

| 用例 | 验证目标 | 通过条件 |
|---|---|---|
| `CapacityRootCreatedOnce` | root registry | 同一 N root identity 相同，不同 N 不同 |
| `CapacityRootPhysicalLayout` | root object/Layout 容量 | Props=1，inlined=N，Layout capacity=1 |
| `PersistentTransitionDoesNotMutateParent` | prefix 隔离 | 新边创建前后 parent Layout identity/raw slots 不变 |
| `PersistentTransitionUsesFinalCapacity` | 目标 Layout 容量 | 每个 child Layout capacity=N，inlined=N |
| `PropertyTransitionExactHit` | 相同 Shape 复用 | structural HClass identity 相同 |
| `PropertyTransitionDifferentOrder` | 顺序隔离 | `{a,b}` 与 `{b,a}` 不同 |
| `PropertyTransitionAccessorIsolation` | metadata 隔离 | data/getter/setter 不误命中 |
| `PropertyTransitionSymbolRejected` | key 保留边界 | symbol method 整次走现有 extractor 路径 |
| `PropertyTransitionComputedRejected` | provenance 边界 | computed property name 整次走现有 extractor 路径，C transition 计数不变 |
| `PropertyTransitionLegacyLiteralRejected` | fail-closed | 无 provenance 的旧 abc/热补丁记录整次回退 |
| `PropertyTransitionRebuildAfterGC` | 弱缓存生命周期 | 中间节点回收后可重建等价 Shape，无悬挂或语义差异 |
| `PrototypeValuesIndependent` | 值隔离 | 方法函数、homeObject、lexenv 均属于各自 class |
| `ProtoTransitionSameParentHit` | final HClass 复用 | 同 Shape 同 parent identity 相同 |
| `ProtoTransitionDifferentParent` | 继承域隔离 | final HClass identity 不同、Layout/own keys 正确 |
| `ExtendsNullIsolation` | null 域 | null 与 Object.prototype 不同 |
| `BaseOwnPropertiesNotInheritedIntoShape` | base Shape 隔离 | 子类 own Layout 不含 base own key |
| `BasePrototypeGetterOrder` | 可观察时序 | getter 次数、顺序、异常与 flag off 一致 |
| `InheritanceSideEffectsPreserved` | 非 Shape 副作用 | FunctionKind、detector、AOT proto-marker/profile 与 flag off 一致 |
| `InheritanceExplicitFastPathRouting` | 分流来源 | 仅本次 C 命中传 true；AOT/interface/clone/resolve/拒绝路径均传 false |
| `AOTSuppliedRejected` | AOT 边界 | 不进入 registry/tree |
| `PGOEnabledRejected` | ProfileType 隔离 | PGO-capable VM 从初始化起不进入 registry/tree |
| `LatePGOEnableRejected` | 生命周期互斥 | C 已开启时拒绝 post-fork JIT-PGO enable |
| `ElementsRejected` | 首阶段边界 | 整次走现有路径 |
| `FlagOffLegacyIdentity` | 回滚 | 每次独立 HClass/Layout |

### 9.2 集成测试

| 场景 | 验证项 |
|---|---|
| 10,000 个相同 class literals | GC 前后 structural/proto hit、rebuild 数、HClass/Layout 数、值隔离 |
| 同属性不同 base class | parentPrototype 分域与继承查询 |
| 深继承链 / 多 sibling | own Shape 不串、proto chain 正确 |
| literal string getter/setter | descriptor、顺序、transition identity |
| computed/symbol/旧 abc | provenance fallback 计数与现有行为一致，C transition 计数不变 |
| Proxy base / throwing prototype getter | 调用时点、异常、未暴露对象回收 |
| 多 Realm / 多 context | parentPrototype identity 分域，不跨 VM |
| PGO off/on、AOT on/off、JIT-free | lifetime PGO-off 共享；PGO-capable VM 从初始化起回退；late-enable 被拒绝 |
| young/full/concurrent GC | root/weak child 生命周期和 verifier |
| serializer/snapshot | HClass/Layout 字段与 proto chain 一致 |

### 9.3 回归测试

- Test262 class definition、method definition、accessor、computed name、extends、Proxy、descriptor 全套 100%；
- abc producer/consumer 版本矩阵、热补丁、class-literal cache 与 AOT snapshot 对 provenance 的 fail-closed 行为 100%；
- `JSPandaFileTest` 新增 extractor transition 用例并 100% 通过；
- `JS_Hclass_Test` 新增 property/proto transition、capacity 与 GC 用例并 100% 通过；
- `JS_LayoutInfo_Test`、AOT/PGO、serializer/snapshot、GC verifier 100%；
- ArkTS/ArkUI class、继承、decorator、热加载、多 context 相关套件与基线一致。

### 9.4 真机验证

1. 同镜像、应用版本、账号、温度和场景执行 C off/on clean A/B，每组至少 5 次；
2. 输出 root create/hit、property edge hit/create、structural reuse、proto hit/create 与 fallback；
3. 以 extractor 创建路径标签统计 HClass/Layout，组 5/6 仅在标签匹配时归因；
4. full-GC 后分列 HClass shallow、Layout shallow、registry/root/prefix/proto-domain 成本；
5. 分列启动 P50/P95、class definition microbenchmark、GC pause、Region used/committed、RSS/PSS；
6. 前台与后台快照独立报告；
7. 任何 prototype 串扰、base getter 时序变化、对象 slot 错位或启动失败均阻断放行。

---

## 10. 评审检查清单

### 10.1 架构合理性

| 检查项 | 结论 |
|---|---|
| 是否直接使用基类 HClass 作为属性 root | 否 |
| 是否按最终 capacity 分域 | 是 |
| 是否使用现有 property/proto transition | 是 |
| 是否共享属性值 | 否 |
| 是否依赖 exact-match Layout table | 否 |
| 是否依赖方案 B | 否 |

### 10.2 流程正确性

| 检查项 | 结论 |
|---|---|
| Attr builder 是否与现有路径共用 | 是 |
| key/metadata 是否进入 transition identity | 是；rep 固定为 TAGGED 并校验 |
| internal prototype 是否通过 transition 分域 | 是 |
| shared structural HClass 是否禁止原地改 proto | 是 |
| base.prototype 读取时序是否保持 | 是 |
| 准入失败是否整次回退 | 是 |

### 10.3 兼容性与性能

| 检查项 | 结论 |
|---|---|
| AOT/Sendable/dictionary/elements/computed/旧格式是否隔离 | 是；provenance 缺失即回退 |
| object size/inlined offset 是否不变 | 是 |
| PGO/JIT-free 是否分别覆盖 | 是；VM-lifetime 互斥，JIT-free 仍检查 PGO 配置 |
| 组 8 是否排除 | 是 |
| root/prefix/proto-domain 成本是否从收益扣除 | 是 |

### 10.4 风险与回滚

| 检查项 | 结论 |
|---|---|
| prototype 串扰是否有硬阻断 | 是 |
| runtime/build flag 是否默认关闭 | 是 |
| flag 关闭是否恢复现有两阶段行为 | 是 |
| 是否需要对象布局迁移 | 否 |

---

## 11. 评审结论

### 11.1 设计结论

本方案可实施的最终结构是“fail-closed literal provenance + capacity root registry + property transition tree + 显式 fast-path 分流 + parentPrototype proto transition”。直接从基类 prototype 的 HClass 生长会继承基类 own Shape，不是合法实现；在共享 structural HClass 上原地 `SetPrototype` 也不是合法实现。方案只覆盖普通 interpreter-created fast-mode class prototype，constructor static Shape 与其他对象类型保持现状。

### 11.2 放行条件

| 维度 | 条件 |
|---|---|
| 正确性 | own keys、descriptor、slot offset、proto chain 与基线一致 |
| 隔离性 | 不同 base/null/Realm 无 HClass proto 串扰，violation=0 |
| 时序 | Proxy/base.prototype getter 调用次数、顺序、异常一致 |
| 内存 | C 独立 net shallow 为正，组 5/6 有 extractor 标签归因 |
| 性能 | 首次/重复 class definition 与启动满足 §7.4 |
| 边界 | AOT supplied、PGO-capable VM、Sendable、dictionary、elements 未进入 C |
| 回滚 | flag off 执行现有一次性构造与原继承设置 |

### 11.3 工作量与排期

| 工作项 | 设计 | 开发 | 测试 | 小计（人日） |
|---|---:|---:|---:|---:|
| Capacity root registry 与 GC 根 | 2 | 4 | 3 | 9 |
| Attr builder 统一与 property transition extractor | 2 | 5 | 4 | 11 |
| proto transition 继承设置与时序保持 | 3 | 5 | 6 | 14 |
| provenance、AOT/Sendable/elements 边界、Flag 与统计 | 2 | 5 | 4 | 11 |
| PGO/GC/serializer/真机性能验证 | 1 | 2 | 6 | 9 |
| **合计** | **10** | **21** | **23** | **54 人日** |

两名开发并行排期约 6 周：第 1 周完成 provenance producer/consumer 契约；第 2 周完成 registry/root 与 Attr 统一；第 3 周完成 property transition；第 4 周完成显式分流、proto transition 与异常时序；第 5 周完成 AOT/PGO/GC/serializer/旧格式回归；第 6 周完成真机 clean A/B、收益归因与评审关闭证据。

### 11.4 归档状态

本文是独立方案设计归档，不代表实现完成、测试通过或收益已落地。最终放行以 §11.2 的代码与实测证据为准。

---

## 12. 附录

### 12.1 术语表

| 术语 | 含义 |
|---|---|
| structural HClass | 由 capacity 与属性 transition 决定、尚未按 parentPrototype 分域的 HClass |
| final HClass | structural HClass 经 proto transition 后供 prototype 对象持有的 HClass |
| capacity root | 具有目标 in-object capacity、只含 constructor 前缀的 transition 根 |
| property transition | runtime 字典以 key、metadata 匹配；C 固定 TAGGED representation |
| proto transition | 以目标 internal prototype identity 匹配的 HClass 边 |
| extractor path label | 标识 HClass/Layout 由普通 class extractor 创建的诊断标签 |

### 12.2 图表索引

| 图表 | 章节 |
|---|---|
| 现有架构图 | 2.1 |
| 目标架构图 | 3.1 |
| 准入流程 | 4.1 |
| capacity root 创建 | 4.2 |
| property transition 构建 | 4.3 |
| internal prototype 分域 | 4.5 |
| Feature Flag 与回滚 | 4.10 |

### 12.3 冻结源码证据

冻结 revision：`f04900cf951c66c2ea18b2bab5b591d5336c34b9`。

| 事实 | 源码位置 |
|---|---|
| extractor 当前一次性创建 prototype Layout/HClass | `ecmascript/jspandafile/class_info_extractor.cpp:206-245` |
| Attr 为 W/C、accessor 标志、inlined、TAGGED、offset=index | `ecmascript/jspandafile/class_info_extractor.cpp:214-229` |
| extractor BitField 仅有 static/non-static elements 标志，不保留 literal/computed 来源 | `ecmascript/jspandafile/class_info_extractor.h:82-99`；`ecmascript/jspandafile/class_info_extractor.cpp:131-203` |
| class-literal cache 从常量池索引取得 EntityId 后提取 literal | `ecmascript/jspandafile/program_object.cpp:20-52` |
| fast/dictionary 分界 | `ecmascript/jspandafile/class_info_extractor.cpp:214-241` |
| 普通 DefineClass 调用 prototype/constructor HClass 创建 | `ecmascript/jspandafile/class_info_extractor.cpp:392-411` |
| prototype slot 与函数值逐对象写入 | `ecmascript/jspandafile/class_info_extractor.cpp:413-432` |
| constructor descriptor、home object、ProtoOrHClass | `ecmascript/jspandafile/class_info_extractor.cpp:465-475` |
| `ProfileDefineClass` 按 constructor method id 写 constructor、instance、prototype root ProfileType | `ecmascript/pgo_profiler/pgo_profiler.cpp:38-73` |
| JIT post-fork 可启用 PGO profiler 与 profiling stubs | `ecmascript/jit/jit.cpp:57-109`；`ecmascript/js_thread.cpp:930-951` |
| AOT supplied prototype/HClass 三分支 | `ecmascript/jspandafile/class_info_extractor.cpp:478-513` |
| Sendable 使用独立 shared HClass/SLayout 路径 | `ecmascript/jspandafile/class_info_extractor.cpp:348-389` |
| property transition 字典以 key、metadata 查找；representation 仅对 AOT child 进一步校验 | `ecmascript/js_hclass.cpp:358-395`；`ecmascript/js_hclass-inl.h:105-140` |
| 通用新 property 路径 clone 后可直接 AddKey 到共享 parent Layout，因此不能直接用于 persistent builder | `ecmascript/js_hclass-inl.h:426-469` |
| `SetPropertyOfObjHClass` 支持指定 inlined property 数，但仍调用通用追加路径 | `ecmascript/js_hclass-inl.h:482-497` |
| `CopyAndReSort` 可按目标 capacity 复制前缀并重建 sorted index | `ecmascript/object_factory.cpp:3526-3556` |
| `AddPropertyToNewHClassWithoutTransition` 在私有 Layout 上追加当前 key | `ecmascript/js_hclass.cpp:397-418` |
| property transition child 以 weak ref 登记，dictionary 分支按 metadata 保存 | `ecmascript/js_hclass-inl.h:25-63` |
| transition dictionary 的 child value 与 heap metadata 为 weak ref，key 槽为强引用 | `ecmascript/transitions_dictionary.h:109-120` |
| rehash 仅复制 weak value 仍存在的 entry | `ecmascript/js_hclass.cpp:97-124` |
| child `Parent` 仅在 PGO profiler enabled 时由 `UpdateRootHClass` 设置 | `ecmascript/js_hclass-inl.h:330-336` |
| 继承设置解析 base/parentPrototype | `ecmascript/stubs/runtime_stubs-inl.h:1167-1213` |
| 现有路径原地写 constructor/prototype HClass proto | `ecmascript/stubs/runtime_stubs-inl.h:1215-1219` |
| 普通 class 创建后立即调用继承设置，适合传递当前栈上的显式 C 命中结果 | `ecmascript/stubs/runtime_stubs-inl.h:1023-1059` |
| `RuntimeCreateClassWithBuffer` 的 `literalId` 参数用于访问 constant pool cache | `ecmascript/stubs/runtime_stubs-inl.h:1004-1040` |
| prototype 更新后执行 detector、AOT proto-marker 与 profile 处理 | `ecmascript/stubs/runtime_stubs-inl.h:1220-1246` |
| `TransitionProto` 查找/创建 proto transition | `ecmascript/js_hclass.cpp:449-481` |
| `Clone` 支持指定 inlined property 数并复用 Layout | `ecmascript/js_hclass.cpp:227-269` |

### 12.4 数据证据与复算

HClass Dump #22：

统计口径固定为三层：`HClass owner 数` 只表示引用者数量；`distinct LayoutInfo pointer 数` 表示实际物理 Layout 对象数；`可消除物理副本数 = max(distinct LayoutInfo pointer 数 - 1, 0)`。收益不得使用 `HClass owner 数 - 1` 代替。本表的 owner 与 distinct 恰好相等，不代表两者可在其他组通用替换。

| 组 | HClass owner 数 | distinct LayoutInfo pointer 数 | 可消除物理副本数 | Shape | C 归档处理 |
|---|---:|---:|---:|---|---|
| 5 | 822 | 822 | 821 | `{constructor, applyPeer, checkObjectDiff}` | extractor 路径标签确认后计入候选 |
| 6 | 761 | 761 | 760 | `{constructor, applyPeer}` | extractor 路径标签确认后计入候选 |
| 8 | 209 | 209 | 208 | `{init, $super, high, low}` | 无 constructor 前缀，排除 |

来源：`LayoutInfo_Identical_Groups.md:2061-2086,2103-2116`。

紧分配候选上界：

```text
group5 = 821 * (16 + 16 * 3) = 52544 B
group6 = 760 * (16 + 16 * 2) = 36480 B
total  = 89024 B = 86.9375 KiB
```

该值未扣除 capacity root、prefix HClass/Layout、proto-domain HClass/Layout copy，也未包含 HClass 毛收益。最终只报告带 extractor 标签的 clean A/B 净值。

### 12.5 配套归档

- [01-背景.md](01-背景.md)
- [02-需求.md](02-需求.md)
- [03-方案设计.md](03-方案设计.md)
- [05-源码与数据证据.md](05-源码与数据证据.md)
- [08-方案A-GlobalEnv预建内建Shape-Singleton.md](08-方案A-GlobalEnv预建内建Shape-Singleton.md)
- [09-方案B-Proto与Extensible-Transition共享Layout-COW.md](09-方案B-Proto与Extensible-Transition共享Layout-COW.md)

### 12.6 更新历史

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-08-28 | v1.1 | 最终归档：三态 abc provenance + JSPandaFile side table fail-closed；capacity root 与 persistent property transition；栈上显式继承分流；parentPrototype proto transition；覆盖 PGO、GC、旧格式、收益与工作量闭环 |
