# 需求（Requirement）：字符串优化

## 收益预估（明确口径）

快照 string `self_size` 是字符数而非对象尺寸（`rawheap_dump.cpp:651-653`），真实堆占用 ≈126 MiB（数据 83.03 + 头部/对齐 ≈43，对象数 2,281,554）。主体机会与预估：

| 子项 | 基数 | 预估收益 |
|---|---|---|
| 短串（≤16）即时 intern/dedup | 1,238,647 个 / 29.6 MiB（数据 10.75 + 头 18.9） | `dupRatio × 29.6 MiB`，dupRatio 由 `05-插桩patch.md` Patch 1 实测（同类引擎经验区间 20–50%，即 **6–15 MiB**） |
| 大串（>1K） | 数据 32.63 MiB | 应用侧归因（缓存/日志类），非 VM 侧 |
| sliced/concat | 节点数 0 | 无存量，flatten/父串释放子项撤销 |

打桩与验证思路见 `05-插桩patch.md`（dump 侧全量去重率 + 运行时 intern 命中率 + 原型后复测法）。

## 背景与问题
Top13 快照 `broad_categories.string` = 83.03 MiB（5.04%），其中 65.09 MiB 为 name 留空的 string 节点（rawheap_translator 对 string name 留空，已确认）。ArkVM 已有 UTF8 压缩 + GetOrInternString intern，但短字符串内联、未 intern 去重、TreeString flatten、SlicedString 父串释放未覆盖。

## 目标
1. 短字符串内联（header ~16B 固定开销，短 key 数据 2-6B 却占 16-24B）；
2. 提高 intern 命中率（动态拼接、JSON key 去重）；
3. TreeString 及时 flatten；SlicedString 小切片不钉住大父串。

## 非目标
- 不改动字符串语义（===、长度、编码）；
- 不引入新的字符串编码格式。

## 验收标准
1. 拆解 string 83 MiB 构成——**已完成长度桶与类型拆解**（`../../evidence/top13-string-array-census.json`）：≤24 B 桶 20.28 MiB、>1K 桶 32.63 MiB、sliced/concatenated 节点数为 0（flatten/父串释放子项在 Top13 无存量，暂缓）；剩余前置项为 intern 命中率插桩与 >1K 大字符串的持有模块归因；
2. 按长度桶统计短字符串数量与字节，量化内联收益（数据已具备，模型待计算）。

## 关联与依赖
- 依赖 VM 侧插桩（GetOrInternString 命中率）；
- ConstantPool 持有的常量字符串（去重 15.38 MiB）与跨 VM 共享方案（`../../detailed-proposals/constantpool-shared-literal/`）分属不同存量，收益可叠加。