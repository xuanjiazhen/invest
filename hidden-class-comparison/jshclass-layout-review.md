# JSHClass 对象布局优化方案

## 1. 方案概览

ArkVM `JSHClass` 固定占 88 B。Top13 快照包含 819,497 个实例，浅层堆合计 68.775 MiB，占快照浅层堆 4.17%。

方案仅处理四个稀疏字段：

- JIT 关闭构建删除 `DependentInfos`；
- `EnumCache` 按需外置；
- `ProtoChangeMarker` 和 `ProtoChangeDetails` 作为第二阶段条件项按需外置。

第一阶段将 local `JSHClass` 从 88 B 缩减到 72 B。第二阶段缩减到 56 B。`Proto`、`Layout`、`Transitions`、`Parent` 和三个 BitField 保留在主对象中。

| 阶段 | local 单实例尺寸 | Top13 毛收益 | aux 成本估算 | Top13 净收益估算 | 工作量 |
|---|---:|---:|---:|---:|---:|
| 第一阶段：删除 `DependentInfos`，外置 `EnumCache` | 72 B | 12.351 MiB | 约 0.189 MiB | 约 12.163 MiB | 55 人日 |
| 第二阶段：继续外置 ProtoChange 两字段 | 56 B | 累计 24.703 MiB | 最坏约 2.382 MiB | 最坏约 22.321 MiB | 累计 71 人日 |

上述收益采用“shared `JSHClass` 保持 88 B”的实现范围。shared 实例占 Top13 的 1.224%，避免为 10,035 个 shared 实例建设 shared-heap ephemeron 支持。

## 2. 现状与量化依据

### 2.1 对象布局

`JSHClass` 的 88 B 由 8 B 对象头、三个 BitField 和八个 Tagged 字段组成。八个 Tagged 字段共 64 B，占对象尺寸 72.7%。

| 偏移 | 大小 | 字段 |
|---:|---:|---|
| 0 | 8 B | TaggedObject header |
| 8 | 4 B | BitField |
| 12 | 4 B | BitField1 |
| 16 | 8 B | Proto |
| 24 | 8 B | Layout |
| 32 | 8 B | Transitions |
| 40 | 8 B | Parent |
| 48 | 8 B | ProtoChangeMarker |
| 56 | 8 B | ProtoChangeDetails |
| 64 | 8 B | EnumCache |
| 72 | 8 B | DependentInfos |
| 80 | 8 B | BitField2 |

Heap Snapshot 中 `hclass` 节点的 `self_size` 为 88 B，只表示 `JSHClass` 自身的浅层大小，不包含字段指向的独立堆对象、业务对象的 in-object property 槽、Region 容量或进程 RSS。

### 2.2 Top13 规模

| 指标 | 实测值 |
|---|---:|
| JSHClass 数 | 819,497 |
| JSHClass 浅层堆 | 68.775 MiB |
| Top13 快照浅层堆 | 1,647.963 MiB |
| JSHClass 占比 | 4.17% |
| 每删除一个 8 B 字段的毛收益 | 6.252 MiB |

逐应用数据见附录 B。

### 2.3 稀疏字段

| 字段 | 实际对象数 | 占 JSHClass 数 | 空槽占比 |
|---|---:|---:|---:|
| `EnumCache` | 6,189 | 0.755% | 99.245% |
| `ProtoChangeMarker` | 15,631 | 1.907% | 98.093% |
| `ProtoChangeDetails` | 12,868 | 1.570% | 98.430% |
| `DependentInfos` | JIT 关闭时为 0 | 0 | 100% |

`EnumCache` 已按需创建，但每个 `JSHClass` 仍固定保留 8 B 槽位。`DependentInfos` 用于 JIT lazy-deopt 依赖，JIT 关闭时不承载状态。

### 2.4 保留字段

| 字段 | 保留原因 |
|---|---|
| `Proto` | 原型链查询直接读取 |
| `Layout` | 保存属性名、offset 和 attributes |
| `Transitions` | shape 演化路径直接读取 |
| `Parent` | 与 transition 路径配合，compiled stub 直接读取 |
| 三个 BitField | 保存对象类型、属性模式、稳定性及 AOT/IC 状态 |

外置这些字段会进入高频属性访问、对象创建或 transition 路径，不属于本方案范围。

## 3. 设计

### 3.1 分阶段布局

```text
当前 local JSHClass：88 B

第一阶段：72 B
  删除 DependentInfos                         -8 B
  外置 EnumCache                              -8 B

第二阶段：56 B
  外置 ProtoChangeMarker / ProtoChangeDetails -16 B
```

`DependentInfos` 只在 JIT 关闭构建中删除。该构建不得重新启用 JIT。

### 3.2 HClassAuxDataTable

外置状态通过 VM 级弱表查询，主对象不保留 sidecar 指针。

```text
local JSHClass
  owner address ──lookup──> HClassAuxDataTable
                                ├─ EnumCache
                                ├─ ProtoChangeMarker
                                └─ ProtoChangeDetails
```

约束如下：

1. 表以 `JSHClass` 为弱键。键存活时值保持强可达；键死亡时清除表项和值。
2. 主对象不增加 8 B 回指。增加回指会抵消第一阶段的外置收益。
3. local 堆复用运行时已有的 ephemeron 弱表语义。
4. `MarkProtoChanged` 通过一次表查询取得 EnumCache 和 ProtoChange 状态。
5. 外置状态不写入 snapshot；反序列化后按需建立。
6. shared `JSHClass` 保持 88 B，不访问 local 表。

### 3.3 shared 实例处理

Top13 包含 10,035 个 shared `JSHClass`，占 1.224%。shared 实例保持 88 B 时，收益折减如下：

| 阶段 | 全量外置毛收益 | shared 不外置毛收益 | 折减 |
|---|---:|---:|---:|
| 第一阶段 | 12.505 MiB | 12.351 MiB | 0.153 MiB |
| 第二阶段累计 | 25.009 MiB | 24.703 MiB | 0.306 MiB |

现有 ephemeron visitor 不处理 shared 堆。shared 不外置可删除 17 人日的 shared GC 弱键支持工作。

## 4. 收益与新增开销

### 4.1 第一阶段

local 实例数为 `819,497 - 10,035 = 809,462`。

```text
毛收益 = 809,462 × 16 B = 12.351 MiB
```

第一阶段表值可直接保存 `EnumCache`，无需单独分配 aux 对象。按 6,189 个表项、16 B/entry、负载因子 0.5 估算：

```text
表成本约 6,189 × 32 B = 0.189 MiB
净收益约 12.351 - 0.189 = 12.163 MiB
```

### 4.2 第二阶段

ProtoChange 两字段进入 aux 对象。三个字段集合完全不相交时，表项上限为 34,688；每项按 40 B aux 对象和 32 B 表项估算：

```text
最坏成本约 34,688 × 72 B = 2.382 MiB
净收益下界约 24.703 - 2.382 = 22.321 MiB
```

以上是对象字节估算。最终结果需分别报告 `JSHClass` 毛收益、aux 对象和表实占、GC committed/resident、PSS。

## 5. 影响范围

### 5.1 功能路径

| 路径 | 影响 |
|---|---|
| 属性访问、对象创建、transition | 保留核心字段，不进入 aux 表 |
| `for...in`、`Object.keys/values/entries`、JSON | EnumCache 读取增加表查询 |
| 原型变更 | 第二阶段通过一次表查询读取相关状态 |
| JIT lazy-deopt | JIT 关闭构建删除 `DependentInfos`；JIT 构建保留原布局 |
| GC | local 表按 ephemeron 语义标记和清理 |
| serializer / snapshot | 不保存外置运行时状态 |
| heap dump / rawheap | 元数据需识别新布局尺寸和版本 |

外部可观察语义保持不变，包括属性枚举顺序、枚举缓存失效、`JSON.stringify` 输出和原型修改行为。字节码格式、公开 API 与 SDK 版本不变。

### 5.2 代码改造范围

第一阶段需要处理：

- `JSHClass` 字段和 offset；
- factory 初始化、HClass 复制与 serializer；
- local 弱表及查询/失效接口；
- EnumCache 的 26 处读取点；
- Baseline JIT/AOT stub 的直接 offset 访问；
- snapshot、AOT 和 rawheap metadata 的布局版本；
- heap dump、translator 和相关测试。

第二阶段增加 ProtoChange Marker/Details 迁移、listener 迁移、AOT 通知以及 `MarkProtoChanged` 单次查询。

## 6. 风险与验证

| 风险 | 等级 | 控制条件 |
|---|---|---|
| Baseline JIT/AOT stub 直读 offset | 高 | 覆盖全部直接访问；保留两级 fast path；验证命中率 |
| EnumCache 调用点遗漏 | 高 | 覆盖 for-in、Object.keys、JSON、runtime 和 stub |
| 布局版本混用 | 高 | snapshot、AOT、rawheap metadata 携带版本；不匹配时拒绝加载 |
| local 弱表生命周期 | 中 | 复用 ephemeron 标记和死键清理；验证无泄漏 |
| 运行时重新启用 JIT | 中 | 删除 `DependentInfos` 的构建禁止启用 JIT |
| sidecar 指针抵消收益 | 中 | 主对象不保留回指 |
| 原型变更通知 | 中 | 验证 listener 迁移和 AOT 通知 |

### 6.1 功能验证

- JIT 关闭构建不安装机器码；
- 解释器、IC、PGO 和 AOT 执行；
- 函数和类定义、继承、prototype 变化、属性 transition；
- `for...in`、`Object.keys/values/entries`、JSON；
- full GC、shared GC 和 heap verification；
- HClass 死亡后表项和缓存回收；
- heap dump、rawheap 转换、debugger、profiler、AppSpawn fork；
- 旧布局 snapshot/AOT 产物拒绝加载。

### 6.2 性能与内存验证

| 基准 | 指标 |
|---|---|
| for-in 与 Object.keys/values/entries | 首次和重复枚举耗时 |
| `JSON.stringify` 大对象 | 吞吐 |
| 原型修改密集用例 | `setPrototypeOf` 耗时 |
| 对象创建与属性 transition | 时延与吞吐 |
| GC | young/full/shared GC 标记和清理耗时 |
| 应用冷启动 | 端到端耗时 |
| Baseline JIT stub | 内联 cache 命中率 |
| Top13 两版快照 | 对象数、浅层堆、aux 实占、PSS |

第一阶段合入条件为：主对象减 16 B、净内存收益为正、弱键清理无泄漏、功能用例通过、枚举与 JIT stub 指标达到评审约定阈值。第二阶段沿用同一验收口径。

## 7. 工作量与排期

### 7.1 第一阶段

| 任务 | 设计 | 开发 | 测试 | 小计 |
|---|---:|---:|---:|---:|
| 删除 `DependentInfos` 及 offset 联动 | 1 | 5 | 3 | 9 |
| local `HClassAuxDataTable` | 2 | 5 | 3 | 10 |
| EnumCache 26 处读取点和 stub fast path | 2 | 8 | 6 | 16 |
| 布局版本与拒绝加载 | 1 | 3 | 3 | 7 |
| 诊断工具适配 | 0 | 3 | 2 | 5 |
| 性能基准与内存实测 | 1 | 0 | 7 | 8 |
| **合计** | **7** | **24** | **24** | **55 人日** |

### 7.2 第二阶段

| 任务 | 设计 | 开发 | 测试 | 小计 |
|---|---:|---:|---:|---:|
| ProtoChange 两字段迁移、listener 与 AOT 通知 | 3 | 7 | 6 | 16 |
| **完整范围累计** | **10** | **31** | **30** | **71 人日** |

按 2 名运行时开发、1 名 compiler/GC 开发、1 名测试工程师并行，第一阶段关键路径约 5–7 周；第二阶段增加约 2–3 周。

## 8. 评审决策项

| 编号 | 事项 | 本文取值 |
|---|---|---|
| D1 | `DependentInfos` 的处理 | JIT 关闭构建删除；JIT 构建保留 |
| D2 | ProtoChange 两字段是否纳入首期 | 作为第二阶段条件项 |
| D3 | shared `JSHClass` 的处理 | 保持 88 B，不建设 shared ephemeron 表 |
| D4 | Baseline JIT stub 的验收阈值 | 评审确定命中率和性能阈值 |
| D5 | 布局版本粒度 | snapshot、AOT、rawheap metadata 统一校验 |

---

## 附录 A：源码证据

基线仓库为 `arkcompiler/ets_runtime`，HEAD 为 `4ad6583a30981259b857579c61b5cc83b3530381`。

| 事实 | 源码位置 |
|---|---|
| JSHClass 布局及 88 B 尺寸 | `ecmascript/js_hclass.h:2214-2227` |
| local/readonly/shared 分配尺寸 | `ecmascript/object_factory.cpp:145-184`；`ecmascript/shared_object_factory.cpp:109-180` |
| Heap Snapshot self_size 链路 | `ecmascript/dfx/hprof/heap_snapshot.cpp:677-679`；`ecmascript/js_hclass-inl.h:276-278`；`heap_snapshot_json_serializer.cpp:124` |
| EnumCache 初始化与首次创建 | `ecmascript/js_hclass.cpp:155`；`ecmascript/js_object.cpp:742-750` |
| DependentInfos 的 JIT lazy-deopt 用途 | `ecmascript/jit/jit_task.cpp:308`；`ecmascript/jit/lazy_deopt_dependency.cpp:43-54,227-243` |
| `MarkProtoChanged` 读取 EnumCache/Marker | `ecmascript/js_hclass-inl.h:380-399` |
| serializer 对运行时字段的处理 | `ecmascript/serializer/base_serializer.cpp:178-192` |
| ephemeron 工作项 | `ecmascript/mem/work_manager.h:62-72` |
| WeakLinkedHashMap 标记 | `ecmascript/mem/full_gc-inl.h:128-143,387-422` |
| ephemeron 不动点迭代 | `ecmascript/mem/full_gc.cpp:174-217` |
| 死键表项清理 | `ecmascript/mem/cms_mem/sweep_gc.cpp:217-257` |
| shared 堆被现有 visitor 排除 | `ecmascript/mem/full_gc-inl.h:391`；`sweep_gc_visitor-inl.h:105`；`old_gc_visitor-inl.h:112`；`young_gc_visitor-inl.h:108` |
| shared HClass 创建和不可扩展属性 | `ecmascript/shared_object_factory.cpp:120,131,140,149,159` |
| Baseline JIT stub 直接读取 EnumCache | `ecmascript/compiler/builtins/builtins_object_stub_builder.cpp:838` |
| AOT 版本常量 | `ecmascript/compiler/aot_file/aot_version.h:28-30` |
| rawheap metadata version | `ecmascript/dfx/hprof/script/metadata_generate.py:74` |

### A.1 local ephemeron 语义

`HClassAuxDataTable` 需要“弱键、键存活时强值”的语义。强键会保活 HClass；普通弱值会使活 HClass 的缓存被提前回收。ArkVM 的 `WeakLinkedHashMap` 已通过 `WeakAggregate`、标记不动点迭代和 sweep 清理实现该语义。JSHClass 分配在 non-movable 或 readonly 空间，键地址在生命周期内稳定。

### A.2 shared 边界

现有 WeakLinkedHashMap visitor 对 shared 对象带断言或跳过处理。shared 表需要独立的分配、并发、写屏障和 GC 弱键支持。本文以 shared 主对象不外置为实现范围。

## 附录 B：Top13 原始数据

输入为 `D:\docker\plan\top13` 的 13 个 `.rawheap`，使用官方 `rawheap_translator` 转换。统计脚本为 `team_interop/scripts/analyze_top13_rawheap.py`，结果为 `team_interop/analysis/top13-jit-off/top13-jit-off-estimates.{csv,json}`。

| 应用 | JSHClass 数 | shared JSHClass |
|---|---:|---:|
| alipay_203MB | 58,508 | 23 |
| bilibili_99MB | 23,340 | 8 |
| douyin_495MB | 133,401 | 4,121 |
| gaodeditu_73MB | 27,083 | 12 |
| jingdong_364MB | 83,345 | 722 |
| jrtt_227MB | 68,103 | 2,117 |
| kuaishou_349MB | 76,848 | 126 |
| meituan_206MB | 61,146 | 67 |
| meituanzhongbao_120MB | 43,415 | 38 |
| pinduoduo_288MB | 63,222 | 2,457 |
| taobao_126MB | 32,373 | 51 |
| wechat_130MB | 40,753 | 30 |
| weibo_317MB | 107,960 | 263 |
| **合计** | **819,497** | **10,035** |

所有样本的 `hclass` 观测 `self_size` 均为 88 B。

## 附录 C：计算口径

```text
local JSHClass 数 = 819,497 - 10,035 = 809,462
第一阶段毛收益 = 809,462 × 16 B = 12.351 MiB
第二阶段累计毛收益 = 809,462 × 32 B = 24.703 MiB
第一阶段表成本 = 6,189 × 32 B = 0.189 MiB
第二阶段最坏表项数 = 6,189 + 15,631 + 12,868 = 34,688
第二阶段最坏成本 = 34,688 × 72 B = 2.382 MiB
```

这些数值是当前对象数乘目标布局差并扣除估算表成本的结果。实现后的验收值以两版设备 heap dump、GC committed/resident 和进程 PSS 为准。
