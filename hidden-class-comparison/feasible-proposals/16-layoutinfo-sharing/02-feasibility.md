# 可行性（Feasibility）：LayoutInfo 共享

## 1. 机制现状（源码核验）

| 事实 | 位置 |
|---|---|
| transition 全量复制（含内容不变的 proto/extensible 路径） | `js_hclass.cpp:440,474`；attr 更新复制整组改一槽 `:778-783` |
| 就地变更者（共享后的泄漏风险点） | `UpdateTrackTypeAttr`/`SetSortedIndex`/`SetNotHole`/`SetIsPGODumped`/`SetNormalAttr`（`layout_info-inl.h:67-72,105-111,296-315`） |
| Clone 家族共享同一数组的既有先例 | `JSHClass::Clone` 复用父 Layout（`js_hclass.cpp:220-269`）——共享本身在 ArkVM 已存在且安全运行的场景 |
| 容量/已用长度天然分离 | 数组 length（容量）与 `hclass->NumberOfProps`（已用）分立——slack 追加所需的结构已具备 |
| Layout 槽带同步读屏障 | `ACCESSORS_SYNCHRONIZED_DCHECK_WITH_RB_MODE(Layout, ...)`（`js_hclass.h` ACCESSORS 链）——并发读路径已有同步语义基础 |

## 2. 数据模型（Top13 重建，脚本可复算）

键序列等价去重 -73.8% 数组（54.00 MiB 上界）>> 前缀家族共享增量（+2.35 MiB）。重复来源推断（与既有证据互证）：W-sys/函数 hclass 的**跨 context/global_env 重建**（feasible 02-A1 已观测 prototype 拷贝 ×6）、proto/extensible 防御性拷贝、attr 更新拷贝。

**口径警示**：快照中 attr 是 Smi 无边不可见，模型按「键序列等价」分组——**attr 值不同的等价组（attr 更新拷贝、TrackType 演化差异）会被高估**。全内容等价的真实比例需插桩/dump 侧核验（dump 遍历时可读对象内存，把 attr 值并入内容哈希即可）。上界按 54.00 MiB 表述，期望值待核验折算。

## 3. 设计要点

### 子方向 A：内容共享

1. **族内共享（零成本起步）**：proto/extensible transition 停止 `CopyLayoutInfo`，直接 `SetLayout(parent)`——与 Clone 同型，arrays 只读路径即刻受益；
2. **变更隔离（核心难题）**：共享数组的全部就地变更改「写时复制」或「族内一致化」：
   - `SetSortedIndex`（AddKey 时维护，仅发生在私有追加路径）——族内共享后追加前必须先拷贝，天然私有；
   - `UpdateTrackTypeAttr`（TrackType 单向粗化）——族内一致化语义（同 shape 同演化，V8 field-type generalization 同型）或 COW；
   - `SetNotHole`/`SetIsPGODumped`/attr 更新——依赖 14-B 迁移（PGO 堆外化、标志折叠）后仅剩 TrackType 一类需处理；
3. **跨 context 内容寻址 intern**（增量项）：全局表 keyed by (keys, attrs) 内容哈希 → 新建 LayoutInfo 前查表复用（写时复制保护）——直接吃掉跨 context 重复（54 MiB 上界的主体）。

### 子方向 B：前缀家族共享（V8 slack-append）

链上追加属性时若容量 slack 足够且本族独占 → 原地追加、子 hclass 共享同数组；分支（同父不同键追加）才拷贝。增量仅 ~2.35 MiB，排 A 之后，仅当 A 的变更隔离已就绪时顺手实施。

## 4. 工作量（估计）

| 任务 | 人日 |
|---|---:|
| proto/extensible 零拷贝 + 族内共享 | 5 |
| 变更隔离（COW/族内一致化框架 + TrackType 方案冻结） | 12–18 |
| 跨 context 内容寻址 intern 表（哈希/COW/GC 集成） | 10–15 |
| slack 追加（子方向 B，可选） | 6 |
| 回归（查找/枚举/PGO/AOT/并发/共享 GC） | 12 |
| 插桩与 Top13 复测 | 5 |
| **合计** | **44–56 人日**（A 为主） |

## 5. 风险

| 风险 | 等级 | 控制条件 |
|---|---|---|
| 就地变更跨族泄漏（正确性） | 高 | 变更者清单冻结（5 个写入者逐一处置）；变更隔离未就绪前仅开放「确认只读」路径共享 |
| TrackType 族内一致化的语义证明 | 高 | 现状：transition 拷贝后子族独立演化；一致化需证明「同 shape 演化收敛」或改 COW（二选一冻结） |
| PGO per-hclass dump 与共享冲突（IsPGODumped 位泄漏） | 中 | 依赖 14-B 的 PGO 堆外化迁移 |
| 跨 context intern 表的 GC/并发 | 中 | 表根挂 Runtime；COW 保证唯一所有权后才可变更 |
| 收益高估（attr 不可见） | 中 | dump 侧全内容哈希核验后折算；上界表述 |

## 6. 置信度

综合约 65%：机制有 ArkVM 自身先例（Clone 共享）与 V8 同型（DescriptorArray 家族共享）、数据实测（-73.8% 数组）；扣分项为 attr 不可见导致收益上界偏乐观、变更隔离的 TrackType 语义未证明。前置插桩：dump 侧全内容等价统计 + transition 拷贝点分类计数。
