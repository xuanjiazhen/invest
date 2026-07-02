# 规划：仓颉开源社区 AI 协同开发流程活动指导书

## 1. 交付件

| 文件 | 形式 | 内容 |
| --- | --- | --- |
| `req.spec.md` | 需求原文 | 保留原始输入，作为需求边界。 |
| `plan.spec.md` | 规划说明 | 明确报告、图、演示页的产物结构。 |
| `report.spec.md` | 正文报告 | 输出角色职责、生命周期活动、Issue 状态、交付件模型、平台能力。 |
| `cangjie-community-ai-flow.drawio` | 可编辑图源 | 包含生命周期泳道和交付件平台能力两页。 |
| `cangjie-community-ai-lifecycle.svg` | 图像 | 角色泳道生命周期流程图。 |
| `cangjie-community-ai-deliverables.svg` | 图像 | 交付件与平台能力流程图。 |
| `cangjie-community-ai-flow-slides.html` | 交互式 HTML 幻灯片 | 面向汇报和评审的可视化材料。 |
| `../index.html` | 索引入口 | 仅增加 slides 卡片。 |

## 2. 受众与目标

受众包括项目经理、PMC 成员、各特性 SIG、Doc SIG、QA SIG、CI/CD SIG、Committer 和 Contributor。目标是把半年 STS 版本周期、月度迭代节奏、Issue 生命周期、DesignSpec/SDD 交付件、AI 辅助点和平台看板能力整理成可执行的社区开发活动指导。

## 3. 内容结构

1. 目标和范围：定义适用版本周期、社区协作边界和治理目标。
2. 角色和职责：说明各角色在需求、设计、开发、测试、发布中的责任。
3. 生命周期泳道：用角色泳道展示从洞察规划到发布闭环的活动链路。
4. Issue 状态模型：覆盖外部反馈、仓库 Issue、初期导入、漏洞跟踪、等待提出人确认与超时关闭。
5. DesignSpec/SDD 交付件：对齐功能基本信息、功能规格和约束、功能设计说明书、DT 与测试策略。
6. 平台能力：区分 GitCode、opencsitool、AI Robot、DesignSpec/SDD 评审、CI/CD、QA、文档发布平台的能力。
7. 准入准出：给出迭代入口、测试准入、发布准出的判定口径。

## 4. 审查准则

- 报告和 slides 只呈现目标态内容，不保留修改痕迹说明。
- `index.html` 只链接 HTML slides，不链接 Markdown、drawio、SVG 或其他中间产物。
- 图源与 SVG 同步输出，报告引用 SVG 并给出 drawio 源文件路径。
- 所有平台能力要能映射到至少一个角色、活动或交付件。
- DesignSpec/SDD 章节需要覆盖需求分析、DT、架构影响、接口、兼容、安全、DFX、测试策略和风险。

## 5. 边界

本次输出是流程和平台能力设计，不展开具体系统接口设计、数据库模型、权限模型和平台开发排期。社区角色以当前草稿和仓颉社区 team 划分为参考，实际落地时需要由社区治理组织确认。