# FunctionTemplate compact recipe：Review Log

## Review 基线

- 冻结源码：`f04900cf951c66c2ea18b2bab5b591d5336c34b9`，审计时工作树 clean。
- 原方向：`feasible-proposals/11-functiontemplate-on-demand/`。
- 数据：Top13 legacy snapshots、快手前台/后台新版 snapshots。
- 评审原则：正式方案只保留能够取得收益的最终实现；验证事项仅写入风险的关闭证据。

## 已关闭问题

| ID | 严重度 | 问题 | 当前处理 |
|---|---|---|---|
| R1 | P0 | FunctionTemplate 的真实消费时机不明确 | 源码确认 class definition 首次执行即消费所有方法模板；正式方案采用 compact persistent recipe |
| R2 | P0 | 收益缺少可复算的覆盖率与元数据成本 | 从 ClassLiteral owner 分布复算真实覆盖、recipe 成本和条件净 shallow |
| R3 | P0 | 首次实例化后删除模板会丢失重复类定义配方 | recipe 常驻 Method、Module、Length 与 feedback anchor，重复定义继续创建新函数 |
| R4 | P0 | RawProfileTypeInfoCell 被当成无用默认字段 | 保留每 ordinal feedback slot，维持 Empty -> CELL_0 -> 后续升级和复用语义 |
| R5 | P0 | hot patch 会按单个模板修改 Module/Cell | recipe 保留每方法 Module/Cell；patch 按 Method 与 ordinal 更新 |
| R6 | P0 | Sendable/SharedHeap 未覆盖 | 同域 SharedHeap recipe，禁止 local/shared 跨域引用，沿用 shared allocation与发布语义 |
| R7 | P1 | ClassLiteral 全量新增字段会向零/单模板类收费 | 双 HClass；仅 `N>=2` 类使用 32 B compact 布局，其他类保持 24 B |
| R8 | P1 | side metadata 成本未扣 | 每类 `24 + 24N` B 全额扣除；条件净 `16N - 24C` |
| R9 | P1 | AOT 直接判断 FunctionTemplate | compact slot 保存 Method，AOT 增加 Method 分支读取 offset，不临时重建模板 |
| R10 | P1 | translator 预解析旁路遗漏 | `program_object.cpp` 与 `panda_file_translator.cpp` 两个入口统一使用 compact builder |
| R11 | P1 | legacy/new snapshot 名称不同 | 使用精确 alias：`function_template/class_literal` 与 `ArkInternalFunctionTemplate/ClassLiteral`，重跑 15 份输入 |
| R12 | P1 | Top13 汇总可能被误读为单进程收益 | 明确标记为 13 个独立进程快照的算术汇总；逐应用行保留 |
| R13 | P1 | 与其他内存提案混算 | CSV 和正文只包含 FunctionTemplate 与 recipe 元数据，不含 LayoutInfo、ConstantPool、Interop、Attr packing、Cell 裁剪 |

## 最终评审结论

正式方案确定为：

> 对每个 `N>=2` 的 LocalHeap 或 SharedHeap ClassLiteral，使用专用 compact HClass；literal slot 保存 Method，ClassLiteral 同域 recipe array 按 ordinal 保存 Module、Length 和 RawProfileTypeInfoCell；所有消费者直接读取 recipe，不创建 FunctionTemplate。

条件净 shallow：Top13 汇总 `11.206 MiB`，快手前台 `0.674 MiB`，快手后台 `0.647 MiB`。Top13 不是单进程收益；前后台互不相加。RSS/PSS 尚无 clean A/B 数据，不作换算。

尚未关闭的正确性、并发、GC、性能与物理内存问题统一列在 [03-方案设计.md](03-方案设计.md)“风险与关闭证据”中。
