# LayoutInfo immutable canonical sharing：Review Log

## Review 基线

- 冻结源码：`f04900cf951c66c2ea18b2bab5b591d5336c34b9`，审计时工作树 clean。
- 原方向：`feasible-proposals/16-layoutinfo-sharing/`。
- 数据：Top13 legacy snapshots、快手前台/后台 translated-v2 snapshots。
- 评审原则：正式方案只保留取得收益的最终实现；验证事项统一写入风险与关闭证据。

## 已关闭问题

| ID | 严重度 | 问题 | 当前处理 |
|---|---|---|---|
| R1 | P0 | 原模型仅按 key 序列恢复 Layout，缺 Attr primitive，却描述为内容等价 | legacy 统一标为缺 Attr 上界；快手新版使用 key identity + 完整 Attr word strict model |
| R2 | P0 | 原脚本按有效 key 数重建尺寸，遗漏真实 capacity/slack | 新脚本 fingerprint 包含 self_size 推导的 capacity、ExtraLength 和全部物理槽 |
| R3 | P0 | 相同内容被直接视为可共享，未覆盖原地写 | 最终方案采用 immutable canonical；所有写入口显式 COW |
| R4 | P0 | 已有 transition-family 多 owner 和新增去重混算 | 先按 Layout target 去重；已有多 owner 不计新增 gross |
| R5 | P0 | 跨 VM/SharedHeap 引用域未证明 | 最终方案固定为 per-VM LocalHeap；跨 VM/SharedHeap 排除 |
| R6 | P1 | 原 `54.00/56.35 MiB` 使用错误模型基线 | 重放为真实 Top13 shallow `109.25 MiB`、缺 Attr gross 上界 `70.03 MiB` |
| R7 | P1 | canonical table 成本和保活未处理 | 使用 weak table；给出 16/24/32B entry 敏感性并扣除索引成本 |
| R8 | P1 | snapshot 终态被当作创建、热度或物理收益 | 仅作为终态 shallow census；创建/写入/COW/PSS 不从 snapshot 推断 |
| R9 | P1 | compiler、serializer、AOT fixed-offset 消费者未覆盖 | 物理布局和读取 ABI 不变；写入口统一 COW |
| R10 | P1 | ConstantPool / Native Interop 可能混入收益 | 所有表仅含 LayoutInfo shallow 和 table 条件成本 |

## 2026-08-20 可读性重写（人工意见闭环）

**人工意见**：03 存在大量中间决策过程内容，最终方案只是其中部分，无法理解；01 应如实呈现现状、解释全部问题与前置知识并配示例；02 澄清要做的内容/收益/工作量；03 按模板（`constantpool-shared-literal/ArkTS-ConstantPool-Sparse-Pool-Phase1-Review.md`）重写，重点是修改前/修改后的关键流程与关键数据结构变更。

**闭环结论**：三件套按意见重写——01 重写为「现状 + 前置知识 + 示例」（物理格式、读者/写入者清单各配 JS 示例、transition 共享与复制行为、重复实测数据、GC/并发语义，不含方案边界陈述）；02 收敛为「要做的四件事 + 收益/工作量/风险/验收」；03 按评审模板重组为 12 章，新增修改前/后架构图、三条现状数据流、publish/COW/transition/TrackType/GC/flag 七组流程图与时序图、数据结构变更章（type-state、LayoutKey、weak 表、与既有机制区分）、兼容矩阵、性能分析（含 COW 频率）、风险矩阵与关闭证据、测试计划。方案内容（immutable canonical + per-VM weak 表 + COW）与全部数据、工作量（67 人日）不变；05/06/普查脚本保持原样。

## 最终评审结论

正式方案确定为：

> 同 VM LocalHeap 完整内容 immutable canonical sharing，per-VM weak table，所有后续写入显式 COW。

快手最终方案的理论容量为：前台 gross `8.17 MiB`、16B-table 条件净 shallow `7.74 MiB`；后台 gross `6.76 MiB`、条件净 `6.34 MiB`。Top13 `70.03 MiB gross / 66.03 MiB 条件净`仅为缺 Attr 上界。

不进入正式方案：跨 VM、SharedHeap、prefix-chain、PropertyAttributes packing、ConstantPool 和 Native Interop。

尚未关闭的正确性、GC、COW 成本、性能和物理内存问题已统一列在 [03-方案设计.md](03-方案设计.md)“风险与关闭证据”中，不再保留独立验证章节。
