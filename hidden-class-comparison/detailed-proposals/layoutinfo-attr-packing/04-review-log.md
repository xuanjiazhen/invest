# 审视日志（LayoutInfo 属性描述槽压缩）

本文件保存各轮审视记录与闭环意见，不混入正式方案文档。审视对象：01-背景 / 02-需求 / 03-方案设计。

## 第 1 轮：候选期审视（feasible 阶段，2026-08-14）

**审视意见（人工）**：是否会因为对齐等其他因素导致收益与付出不成正比？

**闭环结论**：全量 735,734 个 Layout 逐数组精算（尺寸全部满足 16+16N）：新尺寸 align8(16+12N)，N 为奇数时引入 4 B padding，N≤1 的 75,170 个（10.2%）节省为 0；合计节省 23.17 MiB / 21.2%，相对朴素模型仅损失 1.35 MiB。收益成立，数字已按精算值落稿。

## 第 2 轮：人工审视 TODO（2026-08-15）

**审视意见（人工）**：此方案细化后作为正式方案放到 detailed-proposals 中。

**闭环结论**：已升级为详细方案（本目录 01/02/03），按《架构特性设计模板》重组：新增布局对比、GC/哨兵用例、查找链迁移清单、与 AuxData Sidecar 同批版本策略；工作量按设计/开发/测试拆分为 49 人日、约 5 周。候选期四件套（requirement/feasibility/ADR/feature）内容已全部并入，原 feasible 目录移除。

## 第 3 轮：人工质询（2026-08-16，Attr 位宽事实修正）

**人工质询**：写入的 28 bit 是哪里识别的？除了这 28 bit，是否还有其他地方继续写入后续未使用的位？

**核验结论**：质询成立，原「Attr 有效载荷 = 28 bit」表述错误。完整事实链：

- 编码为裸位透传：`WrapUint64(v) = v | TAG_INT`、`UnwrapToUint64` 取回全部位（`js_tagged_value.h:832-840`）；读取构造 `PropertyAttributes(JSTaggedValue)`（`property_attributes.h:93`）不截位——28 bit 掩码只发生在**初始化写入** `SetPropertyInit` 的 `GetNormalTagged()`；
- 其余写入者整宽写回（`GetTaggedValue()`）：`SetSortedIndex`（bit28-37，`AddKeyCommon` 每次加属性都维护，`layout_info-inl.h:105-111,351-353`）、`SetNormalAttr`/`UpdateTrackTypeAttr`（保留高位）、`SetNotHole`（bit39）、`SetIsPGODumped`（bit40，PGO dump 路径 `layout_info.cpp:195,217`）、record const 标记（bit38，`runtime_stubs-inl.h:835`）；
- 即存活 LayoutInfo 的 Attr 槽常态携带 38-41 bit，**4 B raw 无损前提不成立**。

**方案修正**（01/02/03 已同步）：分 A/B 两档——A 档 6 B raw 无损（精算 10.42 MiB/9.5%，对齐损耗大）；B 档 4 B raw 为目标形态（23.17 MiB/21.2% 维持），前提是迁移 13 个运行时位：SortedIndex（推荐 Key 区 hash 有序化，V8 同型）、IsConstProps/IsNotHole（折进 SharedFieldType 空余编码）、IsPGODumped（PGO 会话级堆外集合）。B 档 SortedIndex 迁移设计冻结前不进入开发，需求风险表已加对应条目。

## 审视结论汇总

3 轮 3 项意见全部闭环。遗留：B 档 SortedIndex 迁移设计冻结、与 AuxData Sidecar 的合批排期，均在架构评审时确认。

## 第 3 轮：Kuaishou 后台 full-GC 快照复核

**评估口径**：使用同一 API 26 `rawheap_translator` 2.0.0 转换 Kuaishou 前台与后台 rawheap；后台为应用进入后台并执行全量 GC 后的独立存活堆。Layout 按 HClass 的 `Layout` 目标节点去重，逐数组应用 `old=16+16N`、`new=align8(16+12N)`，不与 Top13 汇总混算。冻结数据见 `evidence/kuaishou-background-paired-census.json`。

| 指标 | 前台 Kuaishou | 后台 full-GC Kuaishou | 后台相对前台 |
|---|---:|---:|---:|
| 去重 Layout 数 | 69,744 | 62,491 | -7,253 |
| 属性数 | 779,837 | 686,410 | -93,427 |
| 当前 Layout 浅层堆 | 13,593,296 B（12.964 MiB） | 11,982,416 B（11.427 MiB） | -1,610,880 B |
| 4 B/属性毛收益 | 3,119,348 B（2.975 MiB） | 2,745,640 B（2.618 MiB） | -373,708 B |
| 8 B 对齐损失 | 154,700 B（0.148 MiB） | 146,912 B（0.140 MiB） | -7,788 B |
| 浅层净收益 | 2,964,648 B（2.827 MiB） | 2,598,728 B（2.478 MiB） | -365,920 B（-0.349 MiB，-12.3%） |

**结论**：后台 full-GC 缩小了存活 Layout 人口，绝对净收益随之下降；后台逐数组净降幅仍为当前 Layout 浅层堆的 21.69%，与前台 21.81% 一致，**不改变属性描述槽压缩方案可行结论**。净收益已逐对象扣除 8 B 对齐，不需要 side table/bitmap/index；对象头在新旧公式中均保留。GC 扫描时间、Region 碎片和 RSS/PSS 不属于 snapshot 浅层净收益，仍需实现后 A/B。该存活态尺寸模型置信度高。
