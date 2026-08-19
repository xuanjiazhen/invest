# 需求（Requirement）：LayoutInfo 共享（内容去重 + 家族前缀共享）

## 背景与问题

`LayoutInfo` 在**每次 transition 时全量复制**（`CopyLayoutInfo`，`js_hclass.cpp:440,474,676,778`），包括内容根本不变的路径：proto transition（:474）与 extensible transition（:440）复制出**逐字节相同**的数组；属性 attr 更新 transition（:778-783）复制整组只为改一个 attr 槽。防御性拷贝的根因是 LayoutInfo 会被**就地变更**（`UpdateTrackTypeAttr`/`SetSortedIndex`/`SetNotHole`/`SetIsPGODumped`，见 layoutinfo-attr-packing 01-背景 §3.1 写入者清单）——共享会让变更跨 hclass 泄漏。

Top13 快照重建模型（`scripts/layout_family_sharing_model.py`、`evidence/top13-layout-sharing-model.json`，从 element 边恢复每条 Layout 的有序键序列，键为 interned 字符串、边序号即属性序）：

| 指标 | 数组数 | 字节 |
|---|---:|---:|
| 现状（键序列可恢复子集，覆盖 98.4% 数组 / 78.9% 字节；符号键大数组未覆盖） | 723,691 | 86.21 MiB |
| 键序列等价去重后 | **189,840（-73.8%）** | 32.21 MiB |
| 再加前缀家族共享（V8 式链共享） | **176,232（-75.6%）** | 29.86 MiB |
| **收益上界** | | **去重 ≤54.00 MiB；+家族 ≤56.35 MiB** |

主导项是**内容重复**（每个 context/global_env 重建同 shape、proto/extensible/attr 拷贝），前缀链共享只再贡献 ~2.35 MiB。

## 目标

1. **子方向 A（内容共享，主体）**：内容等价的 LayoutInfo 共享同一数组——proto/extensible transition 停止防御性拷贝，直接继承父数组；跨 context 的同 shape（同键同 attr）经内容寻址 intern 复用；
2. **子方向 B（前缀家族共享，次要）**：V8 slack-append 语义——追加属性时若有容量 slack 且本族独占则原地追加、链上共享，分支点才拷贝；
3. **前置难题（两项共用）**：就地变更隔离——共享后 `UpdateTrackTypeAttr`/`SetSortedIndex`/`SetNotHole`/`SetIsPGODumped`/attr 更新必须改为写时复制或族内一致化。

## 非目标

- 不改每属性编码宽度（layoutinfo-attr-packing 的范围）；
- 不改 JSHClass/JSFunction 布局（冻结硬约束）。

## 验收标准

1. 插桩/复测：新快照 Layout 数组数与字节按等价组模型下降（≥30 MiB 级）；proto/extensible 路径零拷贝；
2. 属性查找/TrackType 演化/PGO dump/枚举序全回归；
3. 共享数组的并发写保护（多线程 hclass 变更）TSAN 通过。

## 关联与依赖

- **与 layoutinfo-attr-packing（14）的顺序**：16 先行会把 14 的基数从 73.6 万降到 ~19 万，14 的收益按比例缩水（B 档 23.17 → ~6 MiB）——**两项应合并排期，先共享后压缩**；
- 依赖 14-B 档的迁移项（IsPGODumped 堆外化等）作为共享的变更隔离前置之一。
