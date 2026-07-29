# 方案提案: EnumCache 字段从 JSHClass 内联移至 Side Table

> 来源: `js_hclass.h:2223`, `js_hclass.cpp:155`, `builtins_object_stub_builder.cpp:838`
> 对比: V8 `src/objects/map.h` — EnumCache 在 V8 Map 中同样为内联字段，但 V8 Map 总大小仅 ~40B

---

## 1. 现状

### JSHClass 中 EnumCache 字段

```
js_hclass.h:2223:
  ACCESSORS_DCHECK(EnumCache, ENUM_CACHE_OFFSET, DEPENDENT_INFOS_OFFSET, IsString);

偏移: 64 字节 (第 7 个 TaggedPtr 字段)
大小: 8 字节
初始化: JSTaggedValue::Null() (js_hclass.cpp:155)
类型:  TaggedPtr → EnumCache 或 Null
```

### 访问点 (3 处关键路径)

| 调用点 | 文件:行号 | 频率 | 场景 |
|--------|----------|------|------|
| `GetOrCreateEnumCacheFromHClass` | `builtins_object_stub_builder.cpp:838` | 每个 for-in 首次 | **Baseline JIT stub** |
| `MarkProtoChanged` | `js_hclass-inl.h:385` | 原型变化时 | GC / AOT |
| `JSON.stringify` | `json_stringifier.cpp:953` | 每次序列化 | 运行时 |

### 当前行为

```
EnumCache 已惰性，但字段槽未惰性:

JSHClass 创建 → SetEnumCache(Null)  ← 字段槽始终占用 8B
for-in 首次 → GetOrCreateEnumCacheFromHClass() → 创建 EnumCache 对象 → 填入字段
后续 for-in → GetEnumCacheOwn(thread, hclass) → 直接读字段 (O(1))
```

## 2. 优化方案: Side Table

### 方案概述

将 EnumCache 从 JSHClass 的内联字段移到全局 Hash Map (key=JSHClass*, value=EnumCache*)。

```
优化前:
  JSHClass (88B)
    ...
    64: EnumCache ptr (8B)  ← 始终占用
    ...

优化后:
  JSHClass (112B)            ← 减少 8B
    ...
    64: [移除]
    ...

  Global Hash Map:
    JSHClass* → EnumCache*   ← 仅在使用 for-in 的 HClass 中存在
```

### 兼容性分析

#### 2.1 Baseline JIT Stub 路径 (`builtins_object_stub_builder.cpp:838`)

这是最大的兼容性挑战——当前代码在 baseline JIT 生成的机器码中**直接通过偏移量访问 EnumCache 字段**:

```cpp
GateRef enumCache = GetOrCreateEnumCacheFromHClass(glue, hclass);
GateRef enumCacheOwn = GetEnumCacheOwnFromEnumCache(glue, enumCache);
//                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
//                    通过固定的 EnumCache::ENUM_CACHE_OWN_OFFSET 偏移
```

**影响**: 改为 side table 后，stub 中的直接偏移访问需改为哈希表查找，引入函数调用开销。

**缓解方案**: 
- Stub 中保留 fast path: 先尝试 JIT 内联 cache (缓存最近访问的 EnumCache 指针在 TLAB 中)
- Fallback: 调用 runtime C++ 函数 `GetEnumCacheSlow()` → 哈希表查找

#### 2.2 MarkProtoChanged 路径 (`js_hclass-inl.h:385`)

```cpp
JSTaggedValue enumCache = jshclass->GetEnumCache(thread);
if (enumCache.IsEnumCache()) {
    EnumCache::Cast(enumCache)->SetInvalidState(thread);
}
```

**兼容性**: 低频路径，改为哈希表查找影响可忽略。

#### 2.3 JSON.stringify 路径 (`json_stringifier.cpp:953`)

同样的内联字段访问，改为哈希表查找有一定性能影响，但 JSON.stringify 本身是重操作，EnumCache 查找开销占比极小。

### 可行性评估

| 维度 | 评估 | 说明 |
|------|------|------|
| **Baseline JIT Stub** | ⚠️ 需修改 | 需引入 2 级 fallback (fast cache → slow hash) |
| **Interpreter** | ✅ 可行 | Interpreter 中修改为函数调用即可 |
| **GC (MarkProtoChanged)** | ✅ 可行 | 低频路径，无性能影响 |
| **并发安全** | ⚠️ 需加锁 | Hash map 需支持并发读写 (或使用 thread-local cache) |
| **共享堆 (SharedHeap)** | ⚠️ 需特殊处理 | 共享 HClass 的 EnumCache 需在共享堆中分配 |

### AOT 编译兼容性

当前 AOT 路径 (`isForAot` 模板参数在 `MarkProtoChanged` 中) 直接访问 `EnumCache` 字段。改为 side table 后，AOT 编译的代码需要通过函数调用而非直接偏移访问——这对 AOT 不是问题，AOT 本身就使用函数调用。

## 3. 预估优化效果

### 3.1 内存节省

```
场景: 京东场景 80,000+ 个 JSHClass（以下按 80,000 下界计算）

优化前: 80,000 × 88B = 7,040,000 B = 6.71 MiB
优化后: 80,000 × 80B = 6,400,000 B = 6.10 MiB

内联字段毛节省: 640,000 B = 0.61 MiB
```

EnumCache 字段占 JSHClass 的 `8/88 = 9.1%`。0.61 MiB 是移除内联字段后的毛节省；净节省需扣除实际属性枚举后产生的 side table 表项和哈希桶占用。对于 80 method class 场景（160 个过渡 JSHClass），内联字段毛节省为 `160 × 8B = 1,280B = 1.25KiB`。

### 3.2 实际收益有限的原因

EnumCache 只是 JSHClass 中 9 个 TaggedPtr 字段的 1 个。更大的冗余来自 ProtoChangeMarker (8B)、ProtoChangeDetails (8B)、DependentInfos (8B)——这三个字段 + EnumCache 共 32B。

**如果一起移除这 4 个字段**: 32B × 160 = 5.1 KB 节省。

### 3.3 更优方案: 组合优化

| 字段 | 当前 | 优化方案 | 节省 | 难度 |
|------|------|---------|------|------|
| **EnumCache** | 内联 8B | Side table (Hash map) | 8B | ⚠️ 中 (stub 修改) |
| **ProtoChangeMarker** | 内联 8B | 合并到 BitField2 (1 bit) + side table | 8B | ✅ 低 |
| **ProtoChangeDetails** | 内联 8B | 移到 side table | 8B | ✅ 低 |
| **DependentInfos** | 内联 8B | 移到 side table | 8B | ✅ 低 |
| **合计** | 32B | — | **32B** | — |

## 4. 建议优先级

考虑到 EnumCache 单独优化的收益有限且需要修改 Baseline JIT Stub (高风险):

1. **先做 ProtoChangeMarker 合并** (低风险, −8B)
2. **再做 DependentInfos / ProtoChangeDetails 外移** (低风险, −16B)
3. **最后做 EnumCache side table** (中等风险, −8B)

前两步按字段删除量可减少 24B/JSHClass，使 JSHClass 从 88B 降至 64B；按 80,000 个 JSHClass 计算，内联字段毛节省为 1.83 MiB。跨引擎比例需在相同版本、架构、编译配置和统计边界下测量。

## 5. 不推荐的替代方案

- **完全移除 EnumCache 字段，for-in 每次遍历 Layout**: 不可行——for-in 是热路径，Layout 遍历 O(n) 不可接受
- **压缩指针 (32-bit)**: 需要全 VM 改造，单独对 EnumCache 做意义不大
