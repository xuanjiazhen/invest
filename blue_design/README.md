# 仓颉社区 AI 开发流程设计（Blue Design）

> 开源社区 & AI 的社区化开发流程、活动指导书

## 目录索引

### 📋 核心文档

| 文件 | 说明 |
|------|------|
| [req.spec.md](./req.spec.md) | **需求规格** — 原始目标、交付件要求、整体思路、角色定义和关键活动描述 |
| [plan.spec.md](./plan.spec.md) | **规划说明** — 轻量链路方案的范围、受众、内容结构和审查准则 |
| [report.spec.md](./report.spec.md) | **方案正文** — 目标设计、对象模型、平台分工、端到端链路、文档状态和风险控制 |
| [blue_design_flow.md](./blue_design_flow.md) | **流程指导书** — 完整的社区化开发流程，涵盖需求→设计→开发→测试→发布全生命周期 |

### 📊 流程与架构图

| 文件 | 说明 |
|------|------|
| [cangjie-community-ai-flow.drawio](./cangjie-community-ai-flow.drawio) | **泳道流程图源文件** — 包含参与角色、关键活动、生命周期的完整流程图（Draw.io 格式，可编辑） |
| [cangjie-community-ai-lifecycle.svg](./cangjie-community-ai-lifecycle.svg) | **生命周期流程图** — 版本发布周期与迭代开发的完整生命周期视图 |
| [cangjie-community-ai-deliverables.svg](./cangjie-community-ai-deliverables.svg) | **交付件视角流程图** — 各阶段交付件及其关系说明 |
| [cangjie-community-ai-flow-slides.html](./cangjie-community-ai-flow-slides.html) | **流程演示幻灯片** — 交互式 HTML 演示文稿 |

### 🎯 快速导航

1. **了解需求背景** → 先看 [req.spec.md](./req.spec.md)
2. **理解整体流程** → 再看 [blue_design_flow.md](./blue_design_flow.md)
3. **查看轻量方案** → 阅读 [plan.spec.md](./plan.spec.md) 和 [report.spec.md](./report.spec.md)
4. **可视化流程** → 打开 [cangjie-community-ai-flow.drawio](./cangjie-community-ai-flow.drawio) 或 [slides](./cangjie-community-ai-flow-slides.html)

### 🔑 关键概念

- **SR/AR Issue** — 系统级/架构级需求粒度，作为设计、开发、测试的主索引
- **ACEHarness + AET** — AI 辅助需求分析、架构设计和功能设计工具链
- **DesignDocs** — 设计资产仓库，承载版本设计资产和全量设计文档
- **DesignReview** — 设计审视平台，负责定时刷新、自动审视、评分和一致性检查
- **SEG** — 安全专家组，负责风险决策和闭环跟踪
