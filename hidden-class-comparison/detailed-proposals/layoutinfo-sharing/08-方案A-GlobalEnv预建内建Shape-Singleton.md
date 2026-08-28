# 方案 A：GlobalEnv 预建内建 Shape Singleton 设计评审

> 本文档归档仅面向引擎固定、可逐字段证明等价的 class-prototype Shape。方案复用现有 `ClassPrototypeClass` 根对象，不引入内容寻址表，不扩大到用户定义 Shape。

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.1 |
| 归档日期 | 2026-08-28 |
| 方案范围 | class prototype `{constructor}` structural HClass |
| 评审维度 | 架构、流程、兼容性、性能、风险、测试、回滚 |
| 实现状态 | 方案归档；未实施，收益与物理内存效果须按本文门槛验证 |

---

## 1. 概述

### 1.1 背景

ArkVM 已在每个 VM 的 `GlobalEnvConstants` 中持有 `ClassPrototypeClass`：`JS_OBJECT` 类型、1 个 in-object 属性，Shape 为 `{constructor}`，并带 class-prototype 与 prototype 标志。

普通 class extractor 仍会为每个只含 `constructor` 的 class prototype 创建一份新 HClass 与一份新 Layout。HClass Dump #22 中：

| 候选组 | HClass owner 数 | distinct LayoutInfo pointer 数 | 可消除物理副本数 | Shape |
|---|---:|---:|---:|---|
| 组 1 | 6,149 | 6,149 | 6,148 | `{constructor}` |

冻结源码的本地 `JSHClass::Initialize` 已默认把 object HClass 的 Layout 指向全局 `EmptyLayoutInfo`；组 4 的对象类型还是 `TaggedArray`，不是本方案的 class-prototype `JS_OBJECT` 创建路径。因此组 4 的 124 个指针不能归因于本方案，本方案不设计第二套空 Layout helper，也不计入组 4 收益。

### 1.2 目标

| 目标 | 验收口径 |
|---|---|
| 消除固定 class-prototype structural Shape 的重复构造 | 精确准入时以现有 `ClassPrototypeClass` 为结构根，再按 parentPrototype 复用 final HClass |
| 保持对象语义 | prototype 对象、属性值、内部 `[[Prototype]]`、HClass 状态均符合准入谓词 |
| 热读取路径零侵入 | 属性查找、枚举、compiler、serializer 不增加分支或间接层 |
| 可回滚 | build flag 与 runtime flag 双开关，默认关闭，关闭时执行现有创建路径 |
| 可观测 | 分别统计 class-prototype structural/proto-transition 命中和拒绝原因 |

### 1.3 范围

**范围内**：

- VM 配置保证整个生命周期不启用 runtime/JIT PGO 时，非 Sendable、非 AOT-supplied、fast-mode class prototype 的精确 `{constructor}` Shape；
- 准入谓词、Feature Flag、计数器、debug 断言和回归验证。

**范围外**：

- 用户或框架定义属性；
- constructor function 的 `{length, name, prototype}` Shape；
- SharedHeap / Sendable HClass；
- dictionary mode、elements Shape、AOT 已提供 HClass；
- PGO profiler enabled 的 class HClass；
- 跨 VM、跨进程共享；同 VM 多 Realm 只共享 structural root，final HClass 按各 Realm 的 `parentPrototype` identity 分域；
- exact-match table、weak table、通用 Layout COW；
- HClass 本身内容不等价时的强行复用。

---

## 2. 现有架构分析

### 2.1 现有架构图

```text
VM 初始化
  |
  +-- GlobalEnvConstants
  |     `-- ClassPrototypeClass -> Layout {constructor}
  |
class literal
  |
  `-- ClassInfoExtractor::CreatePrototypeHClass
        +-- CreateLayoutInfo(N)
        +-- N 次 AddKey
        `-- NewEcmaHClass

```

### 2.2 现有数据流

```text
class Foo {}
  -> extractor 生成 nonStaticKeys[0] = "constructor"
  -> 创建容量 1 的 LayoutInfo
  -> 写入固定 Attr 与 key
  -> 创建新的 class-prototype HClass
  -> 创建 Foo.prototype
  -> 将 Foo 写入 slot 0
  -> 设置 class 继承关系
```

每次 class 声明都可得到相同 Layout 内容，但 HClass 与 Layout 的创建路径没有使用现有全局根对象。

### 2.3 现有架构问题

| 问题 | 影响 |
|---|---|
| 固定 `{constructor}` Shape 重复构造 | 每个 class 产生一份可避免的 HClass 与 Layout 分配 |
| 仅按属性文本判断 HClass 等价 | 可能忽略 JSType、对象大小、inlined capacity、prototype 与状态位 |
| Layout Attr 含 PGO/TrackType 可写位 | 不能把任意相同文本 Layout 直接视为永久只读 singleton |

---

## 3. 目标架构设计

### 3.1 目标架构图

```text
                         +---------------------------+
VM 初始化 -------------->| 现有 GlobalEnvConstants   |
                         | ClassPrototypeClass       |
                         +-------------+-------------+
                                       |
class prototype 精确准入
                |
                v
复用 ClassPrototypeClass structural root
  - extractor 不再分配 structural HClass/Layout
  - 按 parentPrototype 执行 proto transition
  - prototype 对象和值独立
                |
                v
现有读取、GC、compiler 路径
```

### 3.2 架构设计原则

| 原则 | 约束 |
|---|---|
| 复用现有根 | 不增加重复的 GlobalEnv 槽 |
| 完整 structural HClass 等价 | 不以属性名相同替代 HClass 语义等价 |
| 值与 Shape 分离 | 各 prototype 对象仍持有自己的 constructor 值和方法值 |
| VM/Realm 边界 | root 是 per-VM；同 VM Realm 之间由 parentPrototype identity 隔离 final HClass |
| 读取零改动 | `JSHClass::Layout`、TaggedArray 物理格式和固定偏移不变 |
| 失败回退 | 任一准入条件不满足时走现有独立创建路径 |

### 3.3 组件关系

| 组件 | 职责 | 变更性质 |
|---|---|---|
| GlobalEnvConstants | 提供现有 class-prototype HClass 根 | 不增加槽 |
| ClassInfoExtractor | 判定精确 `{constructor}` fast path | 增加准入分支 |
| JSHClass | 承载现有 Layout 指针与状态 | 物理布局不变 |
| LayoutInfo | debug 下拒绝对 canonical class-prototype Layout 的非法写 | 增加诊断断言，不引入通用 COW |
| JSOptions / FeatureConfig | 控制方案启停 | 默认关闭 |
| 统计模块 | 输出命中与拒绝原因 | 仅诊断构建或受控日志 |

---

## 4. 流程设计

### 4.1 Class Prototype 准入流程

#### 4.1.1 冻结源码现有流程

以下代码均来自冻结 revision `f04900cf951c66c2ea18b2bab5b591d5336c34b9`。现有实现没有方案 A 的 Feature Flag、lifetime PGO-off、精确 `{constructor}` 或完整 HClass 等价判断，也不会从 `CreatePrototypeHClass` 返回 `ClassPrototypeClass`。现有 class 创建主流程（含 HybridVM interface 入口）如下：

```text
RuntimeCreateClassWithBuffer
  -> NewClassInfoExtractor
  -> HybridVM interface metadata?
       true  -> DefineInterfaceTypeOwnProperty
                  -> BuildClassInfoExtractorFromLiteral(implementLength=1)
                  -> EntranceForDefineClass
                       -> AOT: DefineClassWithIHClass
                       -> non-AOT: DefineClassFromExtractor
       false -> BuildClassInfoExtractorFromLiteral(full literal length)
                  -> ShouldUseAOTHClass?
                       true  -> DefineClassWithIHClass
                       false -> DefineClassFromExtractor
                             -> CreatePrototypeHClass（无方案 A 准入判断）
                             -> 每次分配 prototype HClass/Layout
                             -> 分配独立 prototype 对象并写属性值
  -> RuntimeSetClassInheritanceRelationship
       -> 对 constructor HClass 原地 SetPrototype(parent)
       -> 对 prototype HClass 原地 SetPrototype(parentPrototype)
```

**入口、interface 与 AOT 分流**：`RuntimeCreateClassWithBuffer` 先创建 `ClassInfoExtractor`，再检查 `instance->IsHybridVm() && MaybeHasInterfacesType(thread, arrayHandle)`。interface 分支由 `DefineInterfaceTypeOwnProperty` 按 `implementLength=1` 构建 extractor，并经 `EntranceForDefineClass` 选择 AOT 或普通路径；非 interface 分支才按完整 literal 长度构建 extractor，再依据 `ShouldUseAOTHClass` 选择 AOT 或普通路径，最后统一设置继承关系。对应 `ecmascript/stubs/runtime_stubs-inl.h:1036-1059`：

```cpp
JSHandle<ClassInfoExtractor> extractor = factory->NewClassInfoExtractor(method);
auto instance = ecmascript::Runtime::GetInstance();
ASSERT(instance != nullptr);
if (instance->IsHybridVm() && MaybeHasInterfacesType(thread, arrayHandle)) {
    DefineInterfaceTypeOwnProperty(thread, cls, base, lexenv, extractor, ihc, chc, arrayHandle, classLiteral);
} else {
    auto literalLength = arrayHandle->GetLength();
    ClassInfoExtractor::BuildClassInfoExtractorFromLiteral(thread, extractor, arrayHandle, literalLength);
    if (ShouldUseAOTHClass(ihc, chc, classLiteral)) {
        classLiteral->SetIsAOTUsed(true);
        cls = ClassHelper::DefineClassWithIHClass(thread, base, extractor, lexenv, ihc, chc);
    } else {
        cls = ClassHelper::DefineClassFromExtractor(thread, base, extractor, lexenv);
    }
}

RETURN_EXCEPTION_IF_ABRUPT_COMPLETION(thread);
RuntimeSetClassInheritanceRelationship(thread, JSHandle<JSTaggedValue>(cls), base);
```

interface 判定不是 `ClassInfoExtractor` 内部状态，而是运行时全局 HybridVM 状态与 literal buffer 尾项的组合条件；对应 `ecmascript/stubs/runtime_stubs-inl.h:961-964`：

```cpp
bool RuntimeStubs::MaybeHasInterfacesType(JSThread *thread, const JSHandle<TaggedArray> &arrayHandle)
{
    return arrayHandle->GetLength() != 0 &&
           arrayHandle->Get(thread, arrayHandle->GetLength() - 1).IsString();
}
```

interface 分支由两个真实函数串接：`DefineInterfaceTypeOwnProperty` 负责构建 extractor、调用入口并定义 interface symbol 属性；`EntranceForDefineClass` 负责 AOT/普通二选一。两段代码分别对应 `ecmascript/stubs/runtime_stubs-inl.h:967-985` 和 `988-1001`：

```cpp
// DefineInterfaceTypeOwnProperty: runtime_stubs-inl.h:977-985
ClassInfoExtractor::BuildClassInfoExtractorFromLiteral(
    thread, extractor, arrayHandle, arrayHandle->GetLength(), ClassKind::NON_SENDABLE, 1);
cls = EntranceForDefineClass(thread, base, lexenv, extractor, ihc, chc, classLiteral);
JSHandle<GlobalEnv> env = thread->GetEcmaVM()->GetGlobalEnv();
JSHandle<JSTaggedValue> interfaceTypeSymbol = env->GetInterfaceTypeSymbol();
JSHandle<JSTaggedValue> interfaceTypeValue(thread, arrayHandle->Get(thread, arrayHandle->GetLength() - 1));
PropertyDescriptor desc(thread, interfaceTypeValue, false, false, false);
JSObject::DefineOwnProperty(thread, JSHandle<JSObject>::Cast(cls), interfaceTypeSymbol, desc);
```

```cpp
// EntranceForDefineClass: runtime_stubs-inl.h:996-1001
if (ShouldUseAOTHClass(ihc, chc, classLiteral)) {
    classLiteral->SetIsAOTUsed(true);
    return ClassHelper::DefineClassWithIHClass(thread, base, extractor, lexenv, ihc, chc);
}
return ClassHelper::DefineClassFromExtractor(thread, base, extractor, lexenv);
```

方案 A 首阶段只允许上面的普通非 AOT、非 interface 分支；interface 分支即使最终调用 `DefineClassFromExtractor` 也固定不准入。

**现有流程节点与代码对应关系**：

| 流程节点 | 冻结源码实现 | 结论 |
|---|---|---|
| 创建 extractor | `runtime_stubs-inl.h:1040` | 先创建空的 `ClassInfoExtractor` |
| HybridVM interface 判定 | `runtime_stubs-inl.h:1043`；条件定义于 `runtime_stubs-inl.h:961-964` | 不是 extractor 内部准入状态 |
| interface extractor 构建 | `runtime_stubs-inl.h:977-979` | `ClassKind::NON_SENDABLE`，`implementLength=1` |
| interface AOT/普通分流 | `runtime_stubs-inl.h:988-1001` | 通过 `EntranceForDefineClass`；两条路径均不属于方案 A fast path |
| 普通 extractor 构建 | `runtime_stubs-inl.h:1046-1047` | 以完整 literal 长度构建 |
| 普通 AOT/非 AOT 分流 | `runtime_stubs-inl.h:1049-1053` | AOT 走 `DefineClassWithIHClass`，非 AOT 走 `DefineClassFromExtractor` |
| prototype HClass/Layout 创建 | `class_info_extractor.cpp:400-405`、`206-245` | 当前非 AOT extractor 路径每次创建 |
| 继承关系调用 | `runtime_stubs-inl.h:1057-1058` | 创建返回后统一进入 `RuntimeSetClassInheritanceRelationship` |
| 继承 proto 写入 | `runtime_stubs-inl.h:1215-1218` | constructor/prototype HClass 当前均原地 `SetPrototype` |

**Sendable 边界**：Sendable class 不进入上述普通分支。它由 `RuntimeCreateSharedClass` 调用 `BuildClassInfoExtractorFromLiteral(..., ClassKind::SENDABLE)` 和 `DefineSendableClassFromExtractor`，对应 `ecmascript/stubs/runtime_stubs-inl.h:1105-1155`；其 HClass 由 `CreateSendableHClass` 在 shared heap 创建，对应 `ecmascript/jspandafile/class_info_extractor.cpp:348-389`。因此 Sendable 是入口级范围隔离，不是 `CreatePrototypeHClass` 内已有的拒绝分支。

**`{constructor}` key 的来源**：extractor 根据 literal 中的非静态成员数分配数组，并无条件在下标 0 写入全局 canonical `constructor` string。无其他 prototype 成员时，`nonStaticKeys.length == NON_STATIC_RESERVED_LENGTH == 1`。对应 `ecmascript/jspandafile/class_info_extractor.h:43-50` 与 `ecmascript/jspandafile/class_info_extractor.cpp:35-74`：

```cpp
static constexpr uint8_t NON_STATIC_RESERVED_LENGTH = 1;
static constexpr uint8_t CONSTRUCTOR_INDEX = 0;

nonStaticKeys = factory->NewOldSpaceTaggedArray(nonStaticNum + NON_STATIC_RESERVED_LENGTH);
nonStaticProperties = factory->NewOldSpaceTaggedArray(nonStaticNum + NON_STATIC_RESERVED_LENGTH);
nonStaticKeys->Set(thread, CONSTRUCTOR_INDEX, globalConst->GetConstructorString());
// ...提取其余 non-static keys/properties...
extractor->SetNonStaticKeys(thread, nonStaticKeys);
extractor->SetNonStaticProperties(thread, nonStaticProperties);
```

**现有 prototype HClass 创建**：`DefineClassFromExtractor` 无条件调用 `CreatePrototypeHClass`，然后分配 prototype 对象。对应 `ecmascript/jspandafile/class_info_extractor.cpp:392-405`：

```cpp
JSHandle<TaggedArray> nonStaticKeys(thread, extractor->GetNonStaticKeys(thread));
JSHandle<TaggedArray> nonStaticProperties(thread, extractor->GetNonStaticProperties(thread));
JSHandle<JSHClass> prototypeHClass = ClassInfoExtractor::CreatePrototypeHClass(
    thread, nonStaticKeys, nonStaticProperties);

JSHandle<JSObject> prototype = factory->NewOldSpaceJSObject(prototypeHClass);
```

`CreatePrototypeHClass` 现有唯一结构分支是 fast/dictionary 分界。fast 分支每次新建 Layout 和 HClass；accessor 只改变当前 Layout 的 Attr，不触发回退。对应 `ecmascript/jspandafile/class_info_extractor.cpp:206-245`：

```cpp
uint32_t length = keys->GetLength();
if (LIKELY(length <= PropertyAttributes::MAX_FAST_PROPS_CAPACITY)) {
    JSHandle<LayoutInfo> layout = factory->CreateLayoutInfo(
        length, MemSpaceType::OLD_SPACE, GrowMode::KEEP);
    for (uint32_t index = 0; index < length; ++index) {
        key.Update(keys->Get(thread, index));
        PropertyAttributes attributes = PropertyAttributes::Default(true, false, true);
        if (UNLIKELY(properties->Get(thread, index).IsAccessor())) {
            attributes.SetIsAccessor(true);
        }
        attributes.SetIsInlinedProps(true);
        attributes.SetRepresentation(Representation::TAGGED);
        attributes.SetOffset(index);
        layout->AddKey(thread, index, key.GetTaggedValue(), attributes);
    }
    hclass = factory->NewEcmaHClass(JSObject::SIZE, JSType::JS_OBJECT, length);
    hclass->SetLayout(thread, layout);
    hclass->SetNumberOfProps(length);
} else {
    hclass = factory->NewEcmaHClass(JSObject::SIZE, JSType::JS_OBJECT, 0);
    hclass->SetIsDictionaryMode(true);
    hclass->SetNumberOfProps(0);
}
hclass->SetClassPrototype(true);
hclass->SetIsPrototype(true);
```

**现有 canonical root**：VM 初始化已经创建与单属性 `{constructor}` 目标 Shape 对应的 `ClassPrototypeClass`，但普通 extractor 当前不读取它。对应 `ecmascript/global_env_constants.cpp:512-516` 与 `ecmascript/object_factory.cpp:2099-2116`：

```cpp
SetConstant(ConstantIndex::CLASS_PROTOTYPE_HCLASS_INDEX,
            factory->CreateDefaultClassPrototypeHClass(hClass));

uint32_t size = ClassInfoExtractor::NON_STATIC_RESERVED_LENGTH;
JSHandle<LayoutInfo> layout = CreateLayoutInfo(size, MemSpaceType::OLD_SPACE, GrowMode::KEEP);
PropertyAttributes attributes = PropertyAttributes::Default(true, false, true);
attributes.SetIsInlinedProps(true);
attributes.SetRepresentation(Representation::TAGGED);
attributes.SetOffset(ClassInfoExtractor::CONSTRUCTOR_INDEX);
layout->AddKey(thread_, ClassInfoExtractor::CONSTRUCTOR_INDEX,
    thread_->GlobalConstants()->GetConstructorString(), attributes);
JSHandle<JSHClass> defaultHClass = NewEcmaHClass(hclass, JSObject::SIZE, JSType::JS_OBJECT, size);
defaultHClass->SetLayout(thread_, layout);
defaultHClass->SetNumberOfProps(size);
defaultHClass->SetClassPrototype(true);
defaultHClass->SetIsPrototype(true);
```

**现有继承写入**：普通 class 创建后，constructor HClass 和 prototype HClass 均被原地写 proto。对应 `ecmascript/stubs/runtime_stubs-inl.h:1191-1219`：

```cpp
// 1191-1213：根据 base 解析 parent 和 parentPrototype，保留异常语义。
ctor->GetTaggedObject()->GetClass()->SetPrototype(thread, parent);

JSHandle<JSObject> clsPrototype(thread, JSHandle<JSFunction>(ctor)->GetFunctionPrototype(thread));
clsPrototype->GetClass()->SetPrototype(thread, parentPrototype);
```

#### 4.1.2 方案 A 的新增准入与代码落点

方案 A 在现有 `DefineClassFromExtractor` 调用 `CreatePrototypeHClass` 的位置增加 `GetOrCreatePrototypeHClass`，而不是修改现有 `CreatePrototypeHClass` 的语义。调用者必须显式提供 `allowPrototypeShapeSharing`：仅 `RuntimeCreateClassWithBuffer` 的普通非 AOT、非 interface 分支传 `true`；interface 分支传 `false`。AOT 和 Sendable 使用各自现有创建函数，不调用该 helper。其余判断均为方案级待实现：

```text
DefineClassFromExtractor(nonStaticKeys, nonStaticProperties)
  |
  `-- GetOrCreatePrototypeHClass                         [方案新增]
        |
        +-- Feature Flag 关闭 --------------------------> CreatePrototypeHClass（现有）
        +-- VM 不满足 lifetime PGO-off -----------------> CreatePrototypeHClass（现有）
        +-- keys.length != NON_STATIC_RESERVED_LENGTH --> CreatePrototypeHClass（现有）
        +-- key[0] identity != constructorString -------> CreatePrototypeHClass（现有）
        +-- canonical root 一次性字段校验未通过 -------> CreatePrototypeHClass（现有）
        `-- 全部满足
              -> 返回 GlobalConstants.ClassPrototypeClass structural root
              -> prototypeShapeShared = true
              -> 本次不分配 prototype HClass/LayoutInfo
```

对应的方案级伪代码如下；函数名与 Flag API 均为待实现接口，不得视为冻结源码已有实现：

```cpp
JSHandle<JSHClass> ClassInfoExtractor::GetOrCreatePrototypeHClass(
    JSThread *thread,
    JSHandle<TaggedArray> &keys,
    JSHandle<TaggedArray> &properties,
    bool allowPrototypeShapeSharing,
    bool &prototypeShapeShared)
{
    prototypeShapeShared = false;
    if (!allowPrototypeShapeSharing ||
        !IsClassPrototypeSingletonEnabled(thread) ||
        !IsPgoDisabledForVmLifetime(thread) ||
        keys->GetLength() != NON_STATIC_RESERVED_LENGTH ||
        !JSTaggedValue::SameValue(thread, keys->Get(thread, CONSTRUCTOR_INDEX),
                                  thread->GlobalConstants()->GetConstructorString()) ||
        !IsValidatedDefaultClassPrototypeRoot(thread)) {
        return CreatePrototypeHClass(thread, keys, properties);
    }

    prototypeShapeShared = true;
    return JSHandle<JSHClass>(thread->GlobalConstants()->GetHandledClassPrototypeClass());
}
```

`IsValidatedDefaultClassPrototypeRoot` 在 VM 初始化完成后对 `JSType`、object size、inlined capacity、`NumberOfProps`、Layout key/Attr、class-prototype/prototype/dictionary/AOT/shared/elements flags 和初始 internal prototype 做一次完整校验并缓存结果；热路径不得先创建一份目标 HClass 再比较。当前 extractor 的 `keys.length == 1` 已排除其他 prototype 方法/accessor；constructor 值在 HClass 创建后才写回 `nonStaticProperties[0]`，因此不存在在 `GetOrCreatePrototypeHClass` 阶段检查 accessor 的独立分支。对应 `ecmascript/jspandafile/class_info_extractor.cpp:400-415`：

```cpp
JSHandle<JSHClass> prototypeHClass = ClassInfoExtractor::CreatePrototypeHClass(
    thread, nonStaticKeys, nonStaticProperties);
JSHandle<JSObject> prototype = factory->NewOldSpaceJSObject(prototypeHClass);
// ...创建 constructor...
nonStaticProperties->Set(thread, 0, constructor);
```

`key[0]` identity 检查仍作为未来 literal/extractor 变更的 fail-closed 防线。

`DefineClassFromExtractor` 增加 `allowPrototypeShapeSharing` 入参和 `prototypeShapeShared` out-param，把本次命中结果沿当前 C++ 调用栈返回给 `RuntimeCreateClassWithBuffer`。方案接口与普通调用点如下；这些参数和返回通道均为方案级待实现：

```cpp
JSHandle<JSFunction> ClassHelper::DefineClassFromExtractor(
    JSThread *thread,
    const JSHandle<JSTaggedValue> &base,
    JSHandle<ClassInfoExtractor> &extractor,
    const JSHandle<JSTaggedValue> &lexenv,
    bool allowPrototypeShapeSharing,
    bool &prototypeShapeShared);

bool prototypeShapeShared = false;
if (ShouldUseAOTHClass(ihc, chc, classLiteral)) {
    classLiteral->SetIsAOTUsed(true);
    cls = ClassHelper::DefineClassWithIHClass(thread, base, extractor, lexenv, ihc, chc);
} else {
    cls = ClassHelper::DefineClassFromExtractor(
        thread, base, extractor, lexenv, true, prototypeShapeShared);
}

RuntimeSetClassInheritanceRelationship(
    thread, JSHandle<JSTaggedValue>(cls), base, ClassKind::NON_SENDABLE, prototypeShapeShared);
```

interface 分支的 `EntranceForDefineClass` 在 non-AOT 路径调用 `DefineClassFromExtractor(..., false, prototypeShapeShared)`，且 out-param 进入前必须为 `false`、返回后必须仍为 `false`。这对应现有 `runtime_stubs-inl.h:967-1001` 的参数扩展。该分支当前实际使用原始 `DefineClassFromExtractor` 四参数接口；`false` 和 out-param 是方案新增参数，不是冻结源码现状。

继承入口只在显式结果为 `true` 时使用 `TransitionProto`，其他路径保持现有原地写入。上述最后一次调用对应现有 `runtime_stubs-inl.h:1057-1059` 的参数扩展；`prototypeShapeShared == true` 时，用 `TransitionProto` 和 `SynchronizedTransitionClass` 替换 `runtime_stubs-inl.h:1217-1218` 对 prototype HClass 的原地 `SetPrototype`，constructor HClass 的 `SetPrototype(parent)` 以及 `runtime_stubs-inl.h:1220-1248` 的 detector、AOT marker 和后处理保持原有顺序。

`RuntimeSetClassInheritanceRelationship` 的其他现有调用点不得推断或继承该布尔值，全部显式传 `false`：`RuntimeResolveClass`（`runtime_stubs-inl.h:886-898`）、`RuntimeCloneClassFromTemplate`（`runtime_stubs-inl.h:916-947`）、Sendable class（`runtime_stubs-inl.h:1105-1155`）、解释器 slow-runtime 转发（`ecmascript/interpreter/slow_runtime_stub.cpp:1171-1174`）以及其他非本次 `DefineClassFromExtractor` 创建路径。这样只有当前一次普通 class 创建命中可以进入 shared-prototype 继承分支。

### 4.2 完整 HClass 等价谓词

准入必须同时满足下列字段；不得只比较 Layout 内容：

| 维度 | 目标值 |
|---|---|
| JSType | `JS_OBJECT` |
| object base size | `JSObject` 固定大小 |
| inlined property capacity | 1 |
| NumberOfProps | 1 |
| Layout | key 为 canonical constructor string；Attr 的 writable/enumerable/configurable、representation、inlined、offset、sorted index 全部一致 |
| HClass flags | class prototype、prototype、dictionary、AOT、shared、elements kind 等与全局根一致 |
| internal prototype | structural root 保持初始化值；parentPrototype 不属于 structural identity |

继承设置必须通过 `TransitionProto(structuralRoot, parentPrototype)` 取得 final HClass，并用 `SynchronizedTransitionClass` 切换当前 prototype 对象；不得直接对共享 `ClassPrototypeClass` 原地写父 prototype。同一 parentPrototype 可命中同一 final HClass，不同 parentPrototype 必须得到不同 final HClass。该流程是方案 A 的必选实现，不是运行期可选回退。

对 `RuntimeSetClassInheritanceRelationship` 的改动只替换现有 `clsPrototype->GetClass()->SetPrototype(parentPrototype)` 这一项。以下既有行为与顺序全部保留：按 base 设置 constructor `FunctionKind`、base constructor 校验、`base.prototype` 读取与异常传播、constructor HClass `__proto__` 设置、`ObjectOperator::UpdateDetectorOnSetPrototype`、AOT constructor/prototype 的 `EnableProtoChangeMarker` 及其后续 profile 处理。prototype HClass 切换完成后再调用 detector 与 marker 逻辑，使其观察 final HClass。

### 4.3 Prototype 对象创建与赋值

```text
取得 canonical ClassPrototypeClass structural root
  -> 分配独立 prototype JSObject
  -> 创建独立 constructor JSFunction
  -> slot[0] 写入该 constructor
  -> 创建各方法函数并写入各自对象
  -> 在既有继承关系设置时点解析 parentPrototype
  -> final = TransitionProto(structural root, parentPrototype)
  -> prototype.SynchronizedTransitionClass(final)
  -> 返回 constructor
```

共享范围是 structural root 与同 parentPrototype 的 final HClass。prototype 对象、constructor 函数、home object、lexical environment 和属性值均不共享。`TransitionProto` 首次创建某个 parentPrototype 分域时按现有实现复制 Layout；该副本必须计入方案成本。方案 B 同时启用时可消除该 copy，但 A 的独立净收益必须在 B 关闭时仍为正。

### 4.4 PGO 与 TrackType 流程

- A runtime flag 只能在 VM 初始化时开启，并要求 runtime PGO 与 JIT-PGO 在该 VM 整个生命周期保持关闭；`ProfileDefineClass` 会按 constructor method id 给 prototype root HClass 写 class-specific `PrototypeId`，不同 class literal 不能共享该 root；
- 冻结实现支持 JIT post-fork 启用 PGO，因此仅检查 class 创建时的当前状态不充分；late-enable hook 检测到 A 已开启时必须拒绝 PGO/JIT-PGO 启用，不能仅让后续 class 回退；
- JIT-free 配置若仍启用 PGO，也必须拒绝 fast path；JIT-free 不等同于 PGO-free；
- 对 canonical class-prototype Layout 调用 `SetNormalAttr`、`SetSortedIndex`、`UpdateTrackTypeAttr`、`SetIsPGODumped`、`SetIsNotHole` 或 `AddKey` 时，debug 构建必须断言失败；
- release 构建中的准入路径不得直接写 canonical root 或其 Layout；需要 owner 级演化时必须走新 HClass/Layout transition；
- 无法证明 owner 状态共享合法的 `{constructor}` case 不得进入 fast path。

### 4.5 Feature Flag 控制流程

```text
进程启动
  -> build flag 未编译：只有现有路径
  -> build flag 已编译：读取 runtime flag（默认 false）
       false -> 现有分配与写入
       true  -> 执行精确准入
                 命中：复用 singleton
                 拒绝：现有路径
```

Flag 在进程生命周期内不可热切换；切换后重启应用。

### 4.6 GC 交互流程

- structural root 及其 canonical Layout 由全局常量根强引用；
- prototype 对象到 HClass、HClass 到 Layout 的 GC 边与现有模型一致；
- 不增加 weak 表、native 裸指针或跨堆引用；
- HClass 和 Layout 对象数下降，但 key/value 的存活关系不变；
- Heap Snapshot 中多个对象指向同一 HClass/Layout 是预期结果。

### 4.7 回滚流程

1. runtime flag 关闭后，新创建对象执行现有路径；
2. 已创建对象保持合法 GC 对象，不需要迁移；
3. 进程重启后恢复全量独立创建；
4. 紧急版本可关闭 build flag，移除准入分支而不改变对象布局或 snapshot schema。

---

## 5. 数据结构设计

### 5.1 关键数据结构

| 数据结构 | 用途 | 是否改变布局 |
|---|---|---|
| `ClassPrototypeClass` | `{constructor}` canonical HClass | 否，直接复用 |
| `JSHClass::Layout` | HClass 到 Layout 的 synchronized 引用 | 否 |
| `LayoutInfo` | key/Attr 双槽属性表 | 否 |
| Feature Flag | 控制精确准入 | 不进入 GC 对象布局 |
| 诊断计数器 | hit/reject/illegal-write | 不进入发布对象布局 |

### 5.2 方案级待实现接口

```cpp
// 名称为方案接口；实现时按 ArkVM 命名规范落位。
bool ClassInfoExtractor::CanUseDefaultClassPrototypeHClass(
    JSThread *thread, const TaggedArray *keys, const TaggedArray *properties);

JSHandle<JSHClass> ClassInfoExtractor::GetOrCreatePrototypeHClass(
    ...,
    bool &prototypeShapeShared);

JSHandle<JSHClass> JSHClass::GetOrCreateClassPrototypeProtoTransition(
    JSThread *thread,
    const JSHandle<JSHClass> &structuralRoot,
    const JSHandle<JSTaggedValue> &parentPrototype);

JSTaggedValue RuntimeStubs::RuntimeSetClassInheritanceRelationship(
    JSThread *thread,
    const JSHandle<JSTaggedValue> &ctor,
    const JSHandle<JSTaggedValue> &base,
    ClassKind kind,
    bool prototypeShapeShared);
```

`GetOrCreatePrototypeHClass` 增加方案级 `bool &prototypeShapeShared` out-param：调用前置 `false`，只有返回 per-VM structural root 时置 `true`；拒绝时保持 `false` 并调用现有 `CreatePrototypeHClass` 逻辑。`RuntimeCreateClassWithBuffer` 把该栈上结果传给紧随其后的 `RuntimeSetClassInheritanceRelationship`；AOT、interface、clone、resolve 和拒绝路径固定传 `false`。继承设置仅在参数为 `true` 时调用 proto transition 并切换当前对象 HClass，不得根据 root identity 或 HClass flags 猜测，也不能继续执行现有原地 `SetPrototype`。

### 5.3 准入统计

| 计数器 | 含义 |
|---|---|
| `class_proto_singleton_hit` | 完整 HClass fast path 命中数 |
| `class_proto_singleton_reject_key` | key/长度不匹配 |
| `class_proto_singleton_reject_attr` | canonical root Attr 不匹配（当前 `keys.length == 1` 路径无独立 accessor 分支） |
| `class_proto_singleton_reject_state` | HClass/proto/heap 状态不匹配 |
| `class_proto_singleton_reject_pgo` | VM 不满足 lifetime PGO-off 约束 |
| `class_proto_transition_hit` | 同 parentPrototype final HClass 命中数 |
| `class_proto_transition_create` | 新 parentPrototype 分域创建数 |
| `singleton_illegal_write` | debug 非零即阻断放行 |

计数器不允许逐事件日志；只在 dump 或退出汇总时输出。

---

## 6. 兼容性分析

### 6.1 兼容性矩阵

| 路径 | 处理 | 风险 |
|---|---|---|
| 普通非继承 class | structural root 后命中 Object.prototype 分域 HClass | 中 |
| `class B extends A` | 按 A.prototype identity 命中或创建 proto transition | 高 |
| `class B extends null` | 独立验证 null prototype | 中 |
| computed method / extra prototype property | `keys.length != 1` 时拒绝 | 低 |
| static 属性 | constructor HClass 不在本方案范围 | 无 |
| AOT supplied HClass | 不进入本方案 | 无 |
| lifetime PGO-off | 可执行 A 准入 | 中 |
| runtime/JIT PGO 可能启用 | VM 初始化时禁用 A；不得创建共享 class root | 低 |
| dictionary mode / elements | 不进入本方案 | 无 |
| Sendable / SharedHeap | 不进入本方案 | 无 |
| serializer / snapshot | 物理边数量变化，字段语义不变 | 低 |
| flag 关闭 | 执行现有创建路径 | 低 |

### 6.2 关键兼容性保证

1. 不改变 TaggedArray、LayoutInfo、JSHClass 的物理字段与固定偏移；
2. 不共享属性值、prototype 对象、constructor 函数、home object 或 lexical environment；
3. 不对 `ClassPrototypeClass` 原地写 proto；不同 parentPrototype 由 proto transition 分域；
4. 异常、准入不明或未来字段新增时一律拒绝 fast path；
5. snapshot 中共享边是实现结果，不改变序列化字段解释。

---

## 7. 性能分析

### 7.1 Layout shallow 收益

LayoutInfo 的紧分配 self size：

```text
self_size = 16 + 16 * capacity
```

本方案唯一计入的候选组：

| 组 | 物理冗余 Layout | capacity | 紧分配毛收益 |
|---|---:|---:|---:|
| 1 | 6,148 | 1 | 196,736 B = 192.12 KiB |
| 合计 | 6,148 | - | 196,736 B = 192.12 KiB |

这是候选上界，不是实现后实测值。组 1 只有带普通 class-extractor 创建路径标签且命中完整准入谓词的对象可计入。组 4 不属于本方案。HClass 节省、分配器 rounding、Region、RSS/PSS 不在该表中。

### 7.2 HClass 与净收益

- extractor fast path 避免每次 class 定义创建一份 structural HClass 与 Layout；
- 每个唯一 parentPrototype 首次命中会创建一份 final HClass，现有 `TransitionProto` 还会复制一份 Layout；
- A 独立净收益必须扣除 global structural root 之外新增的 proto-domain HClass 与 Layout copy；
- HClass shallow 收益必须由带创建路径标签的 dump 统计，不使用组 1 的 Layout 数直接推算；
- 启动期 allocator 调用下降量由命中计数器确认。

### 7.3 CPU 开销

| 操作 | 开销变化 |
|---|---|
| 属性查找/枚举 | 零 |
| compiler/stub 读取 | 零 |
| class 构建 | 增加常数级准入比较，命中时省去 HClass/Layout 分配与 AddKey |
| GC mark | 对象与边数量下降；无 weak 处理开销 |

### 7.4 放行门槛

- 冷启动 P50 回退不超过 1%，P95 不超过 2%；
- class 构建 microbenchmark 不回退超过 1%；
- 组 1 命中后独立 Layout 数下降量与 hit 计数一致；
- `singleton_illegal_write == 0`；
- clean A/B 中 Layout shallow、HClass shallow、Region used/committed、PSS 分列，不从 shallow 推算物理收益。

---

## 8. 风险评估

### 8.1 风险矩阵

| ID | 风险 | 概率 | 影响 | 控制 | 放行证据 |
|---|---|---|---|---|---|
| A-R1 | 继承设置原地修改共享 HClass 的 proto | 中 | 高 | 必选 proto transition + object HClass switch | 不同 base/null/Proxy 用例无串扰 |
| A-R2 | PGO method-id ProfileType 写入共享 root 导致 class identity 冲突 | 中 | 高 | A 与 runtime/JIT PGO VM-lifetime 互斥 | PGO-on VM 中 A 命中为 0；late-enable 被拒绝 |
| A-R3 | HClass flags 或 capacity 不等价 | 低 | 高 | 完整字段谓词 | debug 逐字段断言通过 |
| A-R4 | 组 1 中混有非 class-extractor 创建路径 | 中 | 中 | 仅以创建路径标签命中计入收益 | 标签计数与消失的独立 Layout 数一致 |
| A-R5 | 启动收益未转为 PSS | 中 | 低 | clean A/B 分口径报告 | PSS 中位数单独呈现，不设推算值 |
| A-R6 | 日志进入热路径 | 低 | 中 | 仅汇总计数 | release 默认无逐事件日志 |

### 8.2 关键风险控制

**HClass proto 隔离**：全局 `ClassPrototypeClass` 不能被多个不同父 prototype 的 class 直接原地改写。继承设置必须返回命中或新建的 proto-transition HClass，并切换当前 prototype 对象；实现未完成该动作时 runtime flag 不可见。

**singleton 可写性**：本方案不引入通用 COW。PGO class profiling 直接拒绝；其他任何需要 owner 级 Attr 演化的路径均不具备准入资格。debug 断言用于发现未来写入口，不作为 release 正确性的唯一保障。

---

## 9. 测试计划

### 9.1 单元测试

| 用例 | 验证目标 | 通过条件 |
|---|---|---|
| `DefaultClassPrototypeExactHit` | 固定 Shape 命中 | extractor 返回全局 structural root；继承后对象持有对应 final HClass |
| `DefaultClassPrototypeValueIsolation` | constructor 值不共享 | 两个 prototype slot[0] 指向各自 constructor |
| `DefaultClassPrototypeRejectExtraKey` | 用户方法拒绝 A fast path | 走常规/方案 C 路径 |
| `DefaultClassPrototypeDifferentBase` | proto 隔离 | 两类读取各自 base prototype |
| `DefaultClassPrototypeExtendsNull` | null 继承 | internal prototype 为 null，其他类不受影响 |
| `DefaultClassPrototypeSameBaseTransitionHit` | final HClass 复用 | 同 parentPrototype 的 final HClass identity 相同 |
| `DefaultClassPrototypeProtoRootUnchanged` | structural root 不可变 | 全局 root internal prototype 保持初始化值 |
| `DefaultClassPrototypeExplicitRouting` | 继承分流 | 仅本次 A 命中传 true；AOT/interface/clone/resolve/拒绝路径均传 false |
| `DefaultClassPrototypeInheritanceSideEffects` | 继承副作用保持 | FunctionKind、detector、AOT proto-marker 与 flag off 一致 |
| `DefaultClassPrototypePGORejected` | ProfileType 隔离 | PGO-capable VM 从初始化起 A hit=0，HClass/Layout 按现有路径创建 |
| `DefaultClassPrototypeLatePGOEnableRejected` | 生命周期互斥 | A 已开启的 VM 拒绝 post-fork JIT-PGO enable |
| `SingletonIllegalWriteAssert` | 写入口防护 | debug 构建触发断言 |
| `FlagOffUsesLegacyPath` | 回滚等价 | HClass/Layout 分配 identity 与基线一致 |

### 9.2 集成测试

| 场景 | 验证项 |
|---|---|
| 同 VM 10,000 个空 class | 命中数、对象值隔离、Layout/HClass 数下降 |
| 同 VM 多 Realm / 多 context | structural root 可相同；不同 Realm 的 parentPrototype 产生不同 final HClass，语义与基线一致 |
| 多 Worker | 每 VM 使用自身全局根，不产生跨堆边 |
| AOT 与非 AOT | supplied HClass 路径不进入 A；解释器路径正确 |
| lifetime PGO-off | A 命中、Attr 与执行结果一致 |
| PGO-capable / PGO-on | A 从 VM 初始化起关闭，ProfileType/dump/执行结果与基线一致 |
| late JIT-PGO enable | 与 A 生命周期互斥，启用请求被拒绝并可观测 |
| young/full/concurrent GC | 无 verifier 错误、无悬挂、无 survivor 异常 |
| serializer/snapshot | 字段值一致，共享边数量符合 hit 计数 |

### 9.3 回归测试

- Test262 class、prototype、property descriptor、inheritance 相关用例 100% 通过；
- 既有 `JS_Hclass_Test`、`JS_LayoutInfo_Test`、`JSPandaFileTest` 100% 通过；
- ArkTS/ArkUI class、继承、decorator、热加载相关套件与基线一致；
- debug、release、AOT、PGO、JIT-free 配置分别执行。

### 9.4 真机验证

1. 同镜像、同应用版本、同账号、同场景采集 flag off/on；
2. 每组冷启动与稳态至少 5 次，报告中位数与 P95；
3. 前台和 full-GC 后后台快照独立报告，不相加；
4. 输出 structural/proto-transition hit、创建路径标签、distinct Layout/HClass 及各自 shallow；
5. 输出 Region used/committed、RSS/PSS 与 GC pause；
6. 任何启动失败、非法写、跨类 prototype 串扰均阻断放行。

---

## 10. 评审检查清单

### 10.1 架构合理性

| 检查项 | 结论 |
|---|---|
| 是否复用现有全局根 | 是，不增加重复槽 |
| 是否改变对象物理布局 | 否 |
| 是否引入 exact-match/weak table | 否 |
| 是否共享属性值 | 否 |
| 是否覆盖任意用户 Shape | 否，精确内建白名单 |

### 10.2 流程正确性

| 检查项 | 结论 |
|---|---|
| 完整 structural HClass 准入是否明确 | 是，包含 type/size/capacity/flags/Layout；proto 另行分域 |
| 准入失败是否回退 | 是 |
| PGO/TrackType 风险是否有阻断条件 | 是，PGO class profiling 硬拒绝 |
| flag 关闭是否执行现有路径 | 是 |

### 10.3 兼容性与性能

| 检查项 | 结论 |
|---|---|
| AOT/Sendable/dictionary 是否隔离 | 是 |
| compiler 固定偏移是否不变 | 是 |
| 读取热路径是否不变 | 是 |
| 收益是否按物理 Layout 计算 | 是 |
| shallow 与 PSS 是否分列 | 是 |

### 10.4 风险与回滚

| 检查项 | 结论 |
|---|---|
| 高风险项是否有关闭证据 | 是，A-R1/A-R2/A-R3 |
| 是否可 runtime 关闭 | 是，重启生效 |
| 是否可 build 关闭 | 是 |
| 关闭后是否需要对象迁移 | 否 |

---

## 11. 评审结论

### 11.1 设计结论

本方案的可实施边界是“现有 per-VM structural root + 完整 HClass 等价准入 + parentPrototype proto transition”。组 1 仅作为候选容量，不能替代创建路径命中证据；组 4 明确排除。方案不依赖通用 Layout COW；proto-domain 首次创建沿用现有 Layout copy 并计入成本，任何其他 owner 级可写状态无法证明安全时必须拒绝准入。

### 11.2 放行条件

| 维度 | 条件 |
|---|---|
| 正确性 | class/prototype/descriptor/继承语义与基线一致 |
| 隔离性 | 不同 base、Realm、VM 之间无 HClass proto 串扰 |
| 写安全 | singleton 非法写计数为 0；PGO-capable VM 的 A hit 为 0；late-enable 被拒绝 |
| 内存 | distinct Layout/HClass 下降与命中计数一致 |
| 性能 | 启动 P50 ≤1%、P95 ≤2% 回退 |
| 回滚 | flag off 与基线行为一致 |

### 11.3 工作量与排期

| 工作项 | 设计 | 开发 | 测试 | 小计（人日） |
|---|---:|---:|---:|---:|
| 完整准入谓词与字段断言 | 2 | 3 | 2 | 7 |
| class-prototype fast path 与 proto transition 切换 | 2 | 4 | 4 | 10 |
| Feature Flag、计数器与回滚 | 0 | 1 | 1 | 2 |
| AOT/PGO/GC/真机验证 | 1 | 1 | 5 | 7 |
| **合计** | **5** | **9** | **12** | **26 人日** |

两名开发并行排期为 3 周：第 1 周完成准入与 class-prototype structural 路径；第 2 周完成 proto transition、开关和单元测试；第 3 周完成 AOT/PGO/GC 回归、真机 clean A/B 与评审关闭证据。

### 11.4 归档状态

本文是可独立评审的最终设计归档，不代表实现完成、测试通过或评审签字。实现放行由 §11.2 的证据决定。

---

## 12. 附录

### 12.1 术语表

| 术语 | 含义 |
|---|---|
| Shape | HClass 及其 Layout 描述的对象结构状态 |
| singleton | VM 全局根持有、允许多个对象复用的唯一 HClass 或 Layout |
| distinct Layout | 按 Layout 对象 identity 去重后的物理对象数 |
| owner | 通过 `JSHClass::Layout` 指向某 Layout 的 HClass |
| tight allocation | capacity 等于属性数的 Layout 分配 |
| fast path | 准入全部满足时绕过重复 HClass/Layout 构造的分支 |

### 12.2 图表索引

| 图表 | 章节 |
|---|---|
| 现有架构图 | 2.1 |
| 现有数据流 | 2.2 |
| 目标架构图 | 3.1 |
| class prototype 准入流程 | 4.1 |
| Feature Flag 流程 | 4.5 |

### 12.3 冻结源码证据

冻结 revision：`f04900cf951c66c2ea18b2bab5b591d5336c34b9`。

| 事实 | 源码位置 |
|---|---|
| GlobalEnvConstants 已声明 `ClassPrototypeClass` | `ecmascript/global_env_constants.h:150-158` |
| VM 初始化创建默认 class-prototype HClass | `ecmascript/global_env_constants.cpp:510-516` |
| 默认 HClass 的 `{constructor}` Layout、size、type、flags | `ecmascript/object_factory.cpp:2099-2116` |
| `RuntimeCreateClassWithBuffer` 创建 extractor、检查 HybridVM interface 并执行普通/AOT 分流 | `ecmascript/stubs/runtime_stubs-inl.h:1036-1059` |
| interface metadata 判定条件 | `ecmascript/stubs/runtime_stubs-inl.h:961-964` |
| interface 分支按 `implementLength=1` 构建 extractor，并经 `EntranceForDefineClass` 分流 | `ecmascript/stubs/runtime_stubs-inl.h:977-1001` |
| 本地 object HClass 初始化默认引用全局 `EmptyLayoutInfo` | `ecmascript/js_hclass.cpp:197-203` |
| extractor 当前逐次创建 prototype Layout/HClass | `ecmascript/jspandafile/class_info_extractor.cpp:206-245` |
| 普通 class 路径调用 `CreatePrototypeHClass` 并分配 prototype 对象 | `ecmascript/jspandafile/class_info_extractor.cpp:392-405` |
| prototype slot 写入与 constructor property 定义 | `ecmascript/jspandafile/class_info_extractor.cpp:413-471` |
| 现有路径原地写 constructor/prototype HClass proto | `ecmascript/stubs/runtime_stubs-inl.h:1215-1219` |
| 继承路径在 prototype 更新后执行 detector、AOT proto-marker 与 profile 处理 | `ecmascript/stubs/runtime_stubs-inl.h:1220-1246` |
| `TransitionProto` 查找/创建 proto-domain HClass，并在 miss 时复制 Layout | `ecmascript/js_hclass.cpp:449-481` |
| 对象可通过 synchronized transition 切换 HClass | `ecmascript/mem/tagged_object-inl.h:62-68` |
| Layout 写 API 与 key/Attr 双槽格式 | `ecmascript/layout_info.h:25-89`；`ecmascript/layout_info-inl.h:25-110` |
| Layout 分配按 `2 * capacity` 槽 | `ecmascript/object_factory.cpp:3483-3490` |
| PGO dump 会写 `IsPGODumped` | `ecmascript/layout_info.cpp:191-228` |
| TrackType 更新会原地写 Attr | `ecmascript/layout_info-inl.h:300-315`；`ecmascript/js_hclass.cpp:896-924` |
| `ProfileDefineClass` 按 constructor method id 写 constructor、instance、prototype root ProfileType | `ecmascript/pgo_profiler/pgo_profiler.cpp:38-73` |
| JIT post-fork 可启用 PGO profiler 与 profiling stubs | `ecmascript/jit/jit.cpp:57-109`；`ecmascript/js_thread.cpp:930-951` |

### 12.4 数据证据与复算

HClass Dump #22 明细：

统计口径固定为三层：`HClass owner 数` 只表示引用者数量；`distinct LayoutInfo pointer 数` 表示实际物理 Layout 对象数；`可消除物理副本数 = max(distinct LayoutInfo pointer 数 - 1, 0)`。收益不得使用 `HClass owner 数 - 1` 代替。

| 组 | HClass owner 数 | distinct LayoutInfo pointer 数 | 可消除物理副本数 | Shape |
|---|---:|---:|---:|---|
| 1 | 6,149 | 6,149 | 6,148 | 单属性 `constructor`，Attr Raw `75` |
| 4 | 1,279 | 124 | **本方案计 0** | `TaggedArray`；不是 class-prototype `JS_OBJECT` 创建路径 |

来源：`LayoutInfo_Identical_Groups.md:2010-2020,2051-2059`。

复算：

```text
group1 = (6149 - 1) * (16 + 16 * 1) = 196736 B
group4 = 0
total  = 196736 B = 192.125 KiB
```

对象头与槽公式证据见 `05-源码与数据证据.md:65-78`。该值不含 HClass、allocator rounding、Region、RSS/PSS，也不代表所有候选均能通过准入。

### 12.5 配套归档

- [01-背景.md](01-背景.md)
- [02-需求.md](02-需求.md)
- [03-方案设计.md](03-方案设计.md)
- [05-源码与数据证据.md](05-源码与数据证据.md)
- [09-方案B-Proto与Extensible-Transition共享Layout-COW.md](09-方案B-Proto与Extensible-Transition共享Layout-COW.md)
- [10-方案C-Class-Extractor复用Transition-Tree.md](10-方案C-Class-Extractor复用Transition-Tree.md)

### 12.6 更新历史

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-08-28 | v1.1 | 最终归档：仅复用 class-prototype per-VM structural root；final HClass 按 parentPrototype identity 分域；显式栈上结果控制继承 fast path；组 4 排除；包含 PGO/TrackType、测试、收益与工作量闭环 |
