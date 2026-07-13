# 需求 Issue 到开发完成的轻量方案

## 1. 目标设计

本方案面向 GitCode 使用场景的轻量落地。核心目标是用最少的平台改造，把 SR/AR 粒度需求、AI 辅助设计、设计资产归档、设计审视、代码实现和风险闭环串成可追溯链路。
目标态包括四点：

1. 所有需求以 SR 或 AR 粒度创建 GitCode Issue，Issue 成为后续设计、开发、测试和风险追踪的主索引。
2. ACEHarness 集成 AET 能力后，围绕 Issue 生成需求分析、架构设计和功能设计，并借助 Skill 对内容做多轮审查与优化。
3. DesignDocs 仓库承载两类设计资产：按版本归档的需求分析、架构设计、功能设计；基于代码仓反向生成的全量设计文档。
4. DesignReview 平台围绕 DesignDocs 做定时刷新、自动审视、评分建议、设计与实现一致性检查，并把风险输入开发、测试和 SEG 会议。

成功标准如下：

| 目标 | 判定标准 |
| --- | --- |
| Issue 主索引可追溯 | 每个 SR/AR Issue 能关联版本设计资产、代码仓、PR、评审记录和不一致项。 |
| 设计资产可沉淀 | ACEHarness/AET 输出的设计文档进入 DesignDocs，并按版本、需求、模块建立路径。 |
| 设计质量可度量 | DesignReview 能对版本设计资产给出评分、低分项和改进建议。 |
| 代码一致性可检查 | 代码合入后能识别设计与实现差异，并按当期版本或往期版本给出处理建议。 |
| 风险闭环可执行 | 需要 SEG 跟踪的差异项具备风险说明、责任人、处理结论和测试补充建议。 |

## 2. 对象模型

| 对象 | 定义 | 主键或关联 |
| --- | --- | --- |
| SR Issue | 面向系统级或场景级需求的 GitCode Issue | `SR-ID`、版本、责任 SIG、DesignDocs 路径 |
| AR Issue | 面向架构级或模块级需求的 GitCode Issue | `AR-ID`、父级 SR、模块、DesignDocs 路径 |
| 版本设计资产 | 围绕某个版本、SR/AR 生成的需求分析、架构设计、功能设计 | 版本号、Issue ID、文档类型、评审状态 |
| 全量设计资产 | 基于代码仓反向生成的模块设计、接口设计、依赖关系和实现说明 | 仓库、模块、代码版本、生成时间 |
| 设计审视记录 | DesignReview 对版本设计资产与全量设计资产的评价结果 | Issue ID、评分、低分项、建议、责任人 |
| 一致性差异项 | 设计与实现之间的差异记录 | Issue ID、PR、代码提交、差异类型、风险等级 |
| SEG 跟踪项 | 需要会议决策或跨角色闭环的高风险差异 | 差异项 ID、结论、动作、验收人 |

## 3. 平台分工

| 平台 | 职责 | 关键输出 |
| --- | --- | --- |
| GitCode Issue | 以 SR/AR 粒度登记需求，承载责任人、版本、状态和关联链接 | SR/AR Issue、父子关系、版本字段、PR 链接 |
| ACEHarness | 组织 AI 多 Agent 协作、调用 AET Skill、管理上下文、生成设计草案和审查建议 | 需求分析草案、架构设计草案、功能设计草案、审查意见 |
| AET | 提供结构化设计方法，支撑 RAS、RDS、SDD 类文档生成和检查 | 需求分析、需求设计、软件设计、开发计划检查项 |
| DesignDocs | 保存版本设计资产和全量设计资产，作为设计文档权威仓库 | 版本目录、Issue 目录、模块目录、文档索引 |
| DesignReview | 定时刷新全量设计资产，审视版本设计资产，检查设计与实现一致性 | 评分、低分建议、一致性差异、风险建议 |
| 代码仓 | 承载实现代码、PR、提交记录和反向生成输入 | PR、commit、模块变更、接口变更 |
| SEG 会议 | 对高风险差异做技术决策和闭环跟踪 | 回退结论、设计补充、测试补充、风险接受结论 |

## 4. 从需求 Issue 到开发完成的链路

| 节点 | 输入 | 动作 | 输出 | 主责 |
| --- | --- | --- | --- | --- |
| 1. 创建 SR/AR Issue | 需求描述、版本目标、责任模块 | 按 SR 或 AR 粒度创建 GitCode Issue，填写版本、责任 SIG、父子关系和验收目标 | 可追溯 Issue | 需求提出方、版本 SE |
| 2. 需求分析 | SR/AR Issue | ACEHarness 调用 AET 能力生成需求背景、目标、范围、约束和验收点 | 需求分析文档 | 责任 SIG、ACEHarness |
| 3. 架构设计 | 需求分析、代码仓上下文、全量设计资产 | 生成模块影响、接口影响、依赖变化、兼容性和 DFX 设计 | 架构设计文档 | 责任 SIG、架构审视人 |
| 4. 功能设计 | 架构设计、模块代码、AET 模板 | 生成处理逻辑、关键数据结构、接口契约、异常路径和测试关注点 | 功能设计文档 | 责任开发者、Committer |
| 5. Skill 审查优化 | 三类设计文档 | ACEHarness 使用设计审查、PRD 审查、开发计划检查等 Skill 做质量检查 | 修订建议、设计得分、待确认问题 | ACEHarness、责任 SIG |
| 6. 上传 DesignDocs | 设计文档、Issue 元信息 | 按版本和 Issue 路径提交到 DesignDocs，写入索引和反链 | 版本设计资产 | 责任 SIG |
| 7. DesignReview 自动审视 | 版本设计资产、全量设计资产 | 对比需求设计与代码设计，输出评分、低分项和开发测试输入 | 审视报告、改进建议 | DesignReview |
| 8. 开发实现 | Issue、设计资产、审视建议 | 开发代码，PR 关联 Issue 和 DesignDocs，补充自测说明 | PR、代码提交、自测证据 | 开发者、Committer |
| 9. 合入后一致性检查 | PR、commit、版本设计资产、全量设计资产 | DesignReview 识别实现与设计差异，区分当期版本和往期版本影响 | 一致性差异项、风险建议 | DesignReview、责任 SIG |
| 10. 开发完成确认 | 差异项、PR、测试输入 | 关闭低风险差异，提交高风险差异到 SEG，补充测试或回退不合理实现 | 开发完成记录、SEG 跟踪项 | Committer、QA、SEG |

## 5. DesignDocs 目录建议

DesignDocs 仓库承载版本资产和全量资产两类内容。建议目录如下：

```text
DesignDocs/
  versions/
    <version>/
      issues/
        <SR-or-AR-id>/
          requirement-analysis.md
          architecture-design.md
          function-design.md
          review-summary.md
          links.yaml
  code-derived/
    <repo>/
      <module>/
        overview.md
        interfaces.md
        dependencies.md
        behavior.md
        generated-meta.yaml
  indexes/
    issue-index.yaml
    module-index.yaml
    inconsistency-index.yaml
```

`links.yaml` 至少记录 Issue、父级 Issue、版本、责任 SIG、代码仓、PR、DesignReview 记录和 SEG 跟踪项。`generated-meta.yaml` 记录代码版本、生成时间、生成工具和审视状态。

## 6. DesignReview 能力设计

| 能力 | 输入 | 输出 | 用途 |
| --- | --- | --- | --- |
| 全量设计刷新 | 代码仓、模块配置、生成策略 | `code-derived` 设计资产 | 保持设计文档与代码视图接近。 |
| 版本设计审视 | `versions/<version>/issues/*`、全量设计资产 | 评分、低分建议、缺失项 | 作为开发和测试输入。 |
| 一致性检查 | PR/commit、版本设计资产、全量设计资产 | 差异项、风险等级、建议动作 | 识别设计与实现偏差。 |
| 往期关联说明 | 往期版本设计资产、当前代码变化 | 变更说明、影响范围、关联链接 | 保留历史资产的演进解释。 |
| SEG 跟踪导出 | 高风险差异项 | 会议议题、责任人、建议结论 | 支撑风险决策。 |

设计评分不作为自动阻断条件。低分项优先作为开发补充、测试补充和设计完善输入。阻断动作应由责任 SIG、Committer 或 SEG 根据风险等级决定。

## 7. 状态设计

### Issue 状态

| 状态 | 含义 | 下一步 |
| --- | --- | --- |
| 已创建 | SR/AR Issue 已登记 | 进入 ACEHarness 分析 |
| 设计生成中 | ACEHarness/AET 正在生成或完善设计 | 提交 DesignDocs |
| 设计已归档 | 版本设计资产已进入 DesignDocs | 触发 DesignReview 审视 |
| 审视待处理 | 存在低分项、缺失项或待确认问题 | 责任 SIG 补充设计 |
| 可开发 | 设计审视达到开发准入要求 | 开发和 PR |
| 开发中 | PR 开发、检视、自测 | 合入后一致性检查 |
| 一致性待确认 | 发现设计实现差异 | 低风险关闭或提交 SEG |
| 开发完成 | 差异项已处理，开发证据齐备 | 转入测试或版本后续活动 |

### 一致性差异状态

| 状态 | 含义 | 处理动作 |
| --- | --- | --- |
| 新建 | DesignReview 发现差异 | 分配责任人 |
| 低风险接受 | 差异合理且不影响测试范围 | 记录说明并关闭 |
| 需补充设计 | 实现合理但设计未覆盖 | 更新版本设计资产 |
| 需补充测试 | 实现合理但测试输入不足 | QA 补充测试点 |
| 需回退 | 实现不合理或风险不可接受 | 回退或重做 PR |
| SEG 跟踪 | 需要会议判断 | 输出会议结论并闭环 |

## 8. 角色责任

| 角色 | 责任 |
| --- | --- |
| 需求提出方 | 创建或确认 SR/AR Issue，补充业务目标和验收目标。 |
| 版本 SE | 确认 Issue 粒度、版本归属、父子关系和轻量链路执行状态。 |
| 责任 SIG | 对 ACEHarness/AET 输出的设计内容负责，确认 DesignDocs 归档质量。 |
| 开发者 | 按设计实现代码，关联 Issue、DesignDocs 和 PR 自测证据。 |
| Committer | 审视设计与实现一致性、PR 质量和差异项处理结论。 |
| QA | 根据低分建议、风险建议和差异项补充测试输入。 |
| DesignReview 平台 | 提供评分、差异识别、风险建议和跟踪数据。 |
| SEG | 判断高风险差异的技术处理方向。 |

## 9. 最小落地清单

1. Issue 模板增加 SR/AR 类型、父级 Issue、版本、责任 SIG、DesignDocs 路径、DesignReview 记录字段。
2. ACEHarness 增加面向 SR/AR Issue 的固定任务入口：需求分析、架构设计、功能设计、设计审查。
3. AET 输出映射到三类文档：需求分析文档、架构设计文档、功能设计文档。
4. DesignDocs 建立 `versions/` 与 `code-derived/` 两类目录，并提供索引文件。
5. DesignReview 建立定时刷新、版本设计审视、一致性差异识别和 SEG 跟踪导出能力。
6. PR 模板增加 Issue、DesignDocs、DesignReview 差异项和自测证据链接。
7. SEG 会议增加差异项处理口径：接受、补设计、补测试、回退、延期跟踪。

## 10. 平台建设内容与交互界面

轻量方案的界面不需要做成大而全的项目管理平台，优先围绕 Issue、设计文档、审视结果和差异项提供最短操作路径。

| 平台 | 需要建设的内容 | 主要角色 | 交互界面 |
| --- | --- | --- | --- |
| GitCode Issue | SR/AR Issue 模板、父子 Issue 关系、版本字段、责任 SIG、DesignDocs 链接、DesignReview 链接、PR 反链 | 需求提出方、版本 SE、责任 SIG | Issue 创建页、Issue 详情页、Issue 列表筛选页 |
| ACEHarness | 面向 SR/AR Issue 的任务入口，自动读取 Issue 内容、代码上下文、DesignDocs 关联资产，调用 AET Skill 生成和审查设计 | 责任 SIG、开发者、Committer | Issue 侧边入口、设计生成工作台、审查建议面板 |
| AET Skill | 固化需求分析、架构设计、功能设计、开发计划检查和设计文档审查模板 | 责任 SIG、架构审视人、Committer | Skill 选择器、模板参数表单、检查清单结果页 |
| DesignDocs | 版本设计资产目录、全量设计资产目录、Issue 索引、模块索引、差异项索引和文档反链 | 责任 SIG、开发者、QA | 文档仓库目录页、Issue 设计资产页、模块设计资产页 |
| DesignReview | 全量设计刷新任务、版本设计评分、低分项列表、一致性差异列表、SEG 跟踪导出 | DesignReview 平台、Committer、QA、SEG | 版本审视看板、差异项详情页、SEG 议题导出页 |
| GitCode PR | PR 模板补充 Issue、DesignDocs、DesignReview 差异项、自测证据和设计偏差说明 | 开发者、Committer、QA | PR 创建页、PR 检视页、检查项面板 |

角色视角的最小工作台如下：

| 角色 | 进入入口 | 需要看到的信息 | 主要操作 |
| --- | --- | --- | --- |
| 需求提出方 | GitCode Issue 创建页 | SR/AR 类型、版本、父子关系、验收目标 | 创建 Issue、补充信息、确认需求边界 |
| 版本 SE | Issue 列表与版本筛选页 | SR/AR 分布、责任 SIG、设计状态、阻塞项 | 校正 Issue 粒度、分配责任 SIG、确认版本归属 |
| 责任 SIG | ACEHarness 设计生成工作台 | Issue 内容、代码上下文、历史设计、AET 输出 | 生成设计、处理审查建议、提交 DesignDocs |
| 架构审视人 | DesignReview 版本审视看板 | 架构影响、接口变化、低分项、差异项 | 审视设计、确认风险、提出改进建议 |
| 开发者 | GitCode PR 创建页 | Issue、DesignDocs、审视建议、差异项 | 关联 PR、说明实现方案、补充自测证据 |
| Committer | PR 检视页与差异项详情页 | 设计实现一致性、代码变更、风险建议 | 检视 PR、确认差异处理、决定是否提交 SEG |
| QA | DesignReview 差异项列表 | 低分项、风险建议、需补充测试项 | 补充测试点、确认回归范围、记录验证结果 |
| SEG | SEG 议题导出页 | 高风险差异、建议动作、责任人、影响范围 | 决策接受、补设计、补测试、回退或延期跟踪 |

## 11. 实际操作指导步骤

本节给出一条从 GitCode Issue 创建到开发完成的可执行路径。每一步都需要产出可追溯链接，避免设计、代码、审视结论和风险项分散在不同平台后无法串联。

### 11.1 准备阶段

| 步骤 | 操作 | 责任人 | 完成标准 |
| --- | --- | --- | --- |
| 1 | 在 GitCode 配置 SR/AR Issue 模板，字段包括需求类型、父级 Issue、版本、责任 SIG、责任人、验收目标、DesignDocs 路径、DesignReview 记录、关联 PR | 版本 SE、平台管理员 | 新建 Issue 时能选择 SR 或 AR，并能填写全部追溯字段 |
| 2 | 在 DesignDocs 建立 `versions/`、`code-derived/`、`indexes/` 三类目录 | DesignDocs 维护人 | 仓库中存在版本资产、代码反向资产和索引目录 |
| 3 | 在 ACEHarness 配置固定任务入口：需求分析、架构设计、功能设计、设计审查、开发计划检查 | ACEHarness 维护人、责任 SIG | 责任 SIG 能从 Issue 链接启动对应任务 |
| 4 | 在 DesignReview 配置代码仓、DesignDocs 仓库、版本目录和模块映射 | DesignReview 平台维护人 | 能读取版本设计资产和代码反向生成资产 |
| 5 | 在 PR 模板增加 Issue、DesignDocs、DesignReview 差异项、自测证据字段 | 代码仓维护人、Committer | 新建 PR 时能填写设计与审视追溯链接 |

### 11.2 单个 SR/AR Issue 的执行步骤

| 步骤 | 输入 | 操作 | 输出 | 验收点 |
| --- | --- | --- | --- | --- |
| 1. 创建 Issue | 需求描述、版本目标、责任模块 | 在 GitCode 创建 SR 或 AR Issue，填写父子关系、责任 SIG、验收目标和优先级 | SR/AR Issue | Issue 字段完整，责任 SIG 明确，能进入版本筛选 |
| 2. 启动 ACEHarness 分析 | SR/AR Issue 链接 | 从 Issue 侧边入口启动 ACEHarness，读取 Issue 内容、关联代码仓和历史设计资产 | 分析任务记录 | ACEHarness 能展示 Issue 内容、上下文来源和任务状态 |
| 3. 生成需求分析 | Issue 内容、历史需求、AET RAS 能力 | 生成需求背景、目标、范围、非目标、约束、验收点 | `requirement-analysis.md` 草案 | 责任 SIG 确认需求边界清晰，无明显缺失 |
| 4. 生成架构设计 | 需求分析、代码仓上下文、全量设计资产 | 生成模块影响、接口影响、依赖变化、兼容性、DFX 和风险点 | `architecture-design.md` 草案 | 架构审视人能确认影响范围和关键依赖 |
| 5. 生成功能设计 | 架构设计、模块实现上下文、AET SDD 能力 | 生成处理逻辑、关键数据结构、接口契约、异常路径、测试关注点 | `function-design.md` 草案 | 开发者能据此拆分代码任务和自测项 |
| 6. 执行 Skill 审查 | 三份设计草案 | 使用设计文档审查、PRD 审查、开发计划检查等 Skill 输出检查结果 | 审查建议、待确认问题、质量结论 | 低分项和待确认问题都有责任人和处理意见 |
| 7. 归档 DesignDocs | 三份设计文档、审查结果、Issue 元信息 | 提交到 `versions/<version>/issues/<SR-or-AR-id>/`，更新 `links.yaml` 和索引 | 版本设计资产 | Issue 中回填 DesignDocs 链接，索引可检索到该 Issue |
| 8. 触发 DesignReview 审视 | 版本设计资产、全量设计资产 | DesignReview 读取 DesignDocs，执行评分、缺失项检查和代码设计对照 | 审视报告、低分建议 | Issue 状态能根据审视结果进入“可开发”或“审视待处理” |
| 9. 处理审视建议 | 审视报告、低分项、缺失项 | 责任 SIG 在 ACEHarness 中补充设计，必要时更新三份设计文档 | 新版设计资产、处理记录 | 所有阻塞项关闭或转为明确风险接受 |
| 10. 创建开发 PR | Issue、DesignDocs、审视报告 | 开发者按设计实现代码，在 PR 中填写 Issue、DesignDocs、自测证据和设计偏差说明 | GitCode PR | PR 模板字段完整，Committer 能直接追溯设计依据 |
| 11. PR 检视与自测 | PR、设计资产、审视建议 | Committer 检查代码质量、设计一致性和自测证据，QA 查看测试补充项 | 检视意见、自测结论 | PR 无未处理关键意见，测试输入明确 |
| 12. 合入后刷新设计 | 合入 commit、代码仓、DesignDocs | DesignReview 触发代码反向设计刷新，并对比版本设计资产 | 全量设计资产、差异项 | 差异项按风险等级进入处理列表 |
| 13. 处理一致性差异 | 差异项、PR、设计资产 | 责任 SIG 判断接受、补设计、补测试、回退或提交 SEG | 差异项结论 | 每个差异项都有处理动作和责任人 |
| 14. 开发完成确认 | Issue、PR、DesignDocs、差异项 | Committer 确认开发证据齐备，QA 确认测试输入，版本 SE 更新 Issue 状态 | 开发完成记录 | Issue 进入“开发完成”，追溯链路完整 |

### 11.3 每一步的最小信息要求

| 产物 | 必填信息 | 缺失时处理 |
| --- | --- | --- |
| SR/AR Issue | 类型、版本、责任 SIG、验收目标、父子关系、模块范围 | 退回补充，不能启动 ACEHarness 设计任务 |
| 需求分析文档 | 背景、目标、范围、非目标、约束、验收点 | 标记为审视待处理，由责任 SIG 补充 |
| 架构设计文档 | 模块影响、接口影响、依赖变化、兼容性、DFX、风险点 | 不能进入可开发状态 |
| 功能设计文档 | 处理逻辑、数据结构、接口契约、异常路径、测试关注点 | PR 创建时必须说明缺失原因和补齐计划 |
| DesignReview 审视报告 | 评分、低分项、缺失项、风险建议、责任人 | 不能作为开发输入，需要重新触发审视 |
| PR | Issue 链接、DesignDocs 链接、自测证据、设计偏差说明 | Committer 不进入正式检视 |
| 一致性差异项 | 差异描述、关联 PR、风险等级、建议动作、责任人 | 不能关闭开发完成状态 |

### 11.4 分阶段落地建议

| 阶段 | 建设目标 | 可交付结果 |
| --- | --- | --- |
| 第一阶段：手工串链 | 先用模板和链接把 GitCode Issue、ACEHarness、DesignDocs、PR 串起来 | Issue 模板、DesignDocs 目录、PR 模板、手工回填链接 |
| 第二阶段：半自动生成 | ACEHarness 固化 SR/AR 设计任务，AET 输出三类设计文档 | 一键生成需求分析、架构设计、功能设计草案 |
| 第三阶段：自动审视 | DesignReview 读取 DesignDocs 和代码仓，输出评分与低分建议 | 版本设计审视报告、审视待处理列表 |
| 第四阶段：一致性闭环 | PR 合入后触发全量设计刷新和差异项识别 | 差异项列表、SEG 议题导出、开发完成确认 |

## 12. 主要风险与控制

| 风险 | 表现 | 控制方式 |
| --- | --- | --- |
| Issue 粒度过粗 | 一个 Issue 覆盖多个模块或多个目标 | 版本 SE 在创建阶段确认 SR/AR 粒度，必要时拆分。 |
| AI 设计质量不稳定 | 文档看似完整但缺少代码约束 | DesignReview 对照全量设计资产评分，Committer 做人工确认。 |
| DesignDocs 资产失真 | 文档与代码持续偏离 | 定时刷新全量设计资产，PR 合入后触发一致性检查。 |
| 低分建议无人处理 | 审视结果无法进入开发和测试 | Issue 状态设置为“审视待处理”，处理后才能进入“可开发”。 |
| 往期设计资产被当前实现影响 | 历史文档无法解释新实现 | 生成变更说明并关联到往期设计资产。 |
| 差异项决策不清 | 开发、测试、架构意见不一致 | 高风险差异进入 SEG 跟踪，输出明确结论。 |