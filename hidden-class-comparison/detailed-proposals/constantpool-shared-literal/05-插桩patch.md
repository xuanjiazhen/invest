# 插桩 Patch：对象字面量外置 Backing COW

目的：只量化对象字面量 COW 的输入与结果，不统计 worker、跨 VM 字符串或数组字面量。插桩由 debug/实验构建开关控制，接口名为设计示意，落地时使用目标 revision 的现有 DFX 框架。

## Patch 1：对象字面量模板 eligibility

**文件**：对象字面量模板 materialize 路径、`ecmascript/object_factory.cpp`

对 `Properties` 和 `Elements` 独立记录：

```cpp
// 示意：模板 backing 完成构建后执行一次
Census::RecordObjectLiteralTemplate(
    literalId,
    backingKind,       // PROPERTIES / ELEMENTS
    length,
    alignedBytes,
    eligibility,       // ELIGIBLE / FALLBACK
    fallbackReason);   // EMPTY / DICTIONARY / OVERSIZE / FUNCTION / ACCESSOR / UNSUPPORTED_KIND
```

`literalId` 使用 `(JSPandaFile hash, method/entity id, literal index)` 等稳定点位标识，不使用会被 GC 移动的对象地址作为跨事件主键。

输出按 backing kind、长度桶和 fallback reason 聚合。该打点用于确定对象字面量专属阈值，不能复用数组字面量的 `MAX_READ_ONLY_ARRAY_LENGTH` 作为结论。

## Patch 2：CloneObjectLiteral 命中

**文件**：

- `ecmascript/object_factory.cpp` 的两个 `CloneObjectLiteral`；
- `ecmascript/compiler/new_object_stub_builder.cpp::CloneObjectLiteral`。

census 开启时，compiler stub 可调用轻量 runtime hook，避免维护第二套统计逻辑。每次 clone 分别记录 `Properties` / `Elements`：

```cpp
Census::RecordObjectLiteralClone(
    literalId,
    backingKind,
    isCowHit,
    backingLength,
    alignedBytes);
```

守恒要求：

```text
cloneBackingCount = cowHitCount + deepCopyFallbackCount + emptyBackingCount
avoidedCloneBytes = Σ(cowHit.alignedBytes)
```

函数/访问器 fallback 仍执行原 `CloneProperties(old, env, obj)`，并单独计数，不得记入 avoided bytes。

## Patch 3：首次写脱离

**文件**：普通对象 owner-aware COW 脱离 helper 及其 runtime/stub 调用点。

仅 backing 从 `COWTaggedArray` 转为普通 mutable backing 时记录一次：

```cpp
Census::RecordObjectLiteralDetach(
    backingKind,
    writeKind,         // OVERWRITE / ADD / DELETE / DEFINE / GROW / TO_DICTIONARY / KIND_MIGRATION
    oldLength,
    copiedAlignedBytes);
```

同一实例同一 backing 后续写入不重复计 detach。输出：

```text
detachRate       = detachCount / cowHitCount
detachCopyBytes  = Σ(copiedAlignedBytes)
eventNetBytes    = avoidedCloneBytes - detachCopyBytes
```

这是累计分配/复制口径，不等于 live heap、committed 或 RSS/PSS。

## Patch 4：写路径完整性验证

实验构建增加断言：任何 owner-aware 写入口准备修改 backing 时，如果 backing 仍是 `COWTaggedArray`，必须先经过脱离 helper。对无法建立 owner 的直接 `TaggedArray::Set` 路径，在 COW 来源标记开启时记录调用点或触发 debug fatal。

专项覆盖：

- 覆盖、添加、删除、`defineProperty`；
- symbol key、数值 key、elements grow；
- fast/dictionary 转换；
- elements-kind migration；
- IC/runtime stub/AOT store；
- debugger/反射和内部 helper。

验收要求：所有测试中 `cowDirectWriteViolation == 0`。

## Patch 5：clean A/B

同一应用、同一业务脚本、同一 GC 时点执行：

- A：COW 开关关闭；
- B：COW 开关开启；
- 分别采集前台、后台 full-GC；
- 每组至少重复 5 次，报告中位数与离散度。

并列输出：

```text
cloneCount, cowHitCount, fallbackCount
eligiblePropertiesBytes, eligibleElementsBytes
avoidedCloneBytes, detachCount, detachCopyBytes, eventNetBytes
young/old/nonMovable used bytes
Region used / committed
full-GC live shallow bytes
peak and steady RSS/PSS
clone-path time, first-write time
```

不得用 `js_object` 总量、ConstantPool 的 JSObject/JSArray 混合驻留域或单份快照替代 A/B 净收益。

## 汇总输出示例

```text
objectLiteralCow:
  templates=<n> eligible=<n> fallback=<n>
  clone=<n> cowHit=<n> deepCopy=<n>
  avoidedCloneBytes=<n>
  detach=<n> detachCopyBytes=<n>
  eventNetBytes=<n>
  directWriteViolation=0
  fallback={empty:n, dictionary:n, oversize:n, function:n, accessor:n, unsupported:n}
```

## 数据解释边界

- `eventNetBytes > 0` 只说明累计 backing 分配/复制减少，不证明 RSS/PSS 下降；
- COW backing 位于 NON_MOVABLE 空间，必须单列碎片和 Region commitment；
- `detachRate` 应按 backing kind 与长度分桶，平均值不能用于选择统一阈值；
- clean A/B 是默认开启的必要条件，插桩事件模型不是替代品。
