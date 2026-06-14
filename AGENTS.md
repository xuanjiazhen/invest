# AGENTS.md

本仓库的 AI 辅助编码规范。任何 AI 改动前必须先读取本文。

---

## 调研工作流

每个调研任务必须走完整流水线：

```
req.spec.md → plan.spec.md → report.spec.md → *-slides.html → 加入 index.html
```

| 阶段 | 产物 | 说明 |
|------|------|------|
| 需求 | `req.spec.md` | 原始需求描述，不可篡改 |
| 规划 | `plan.spec.md` | 明确交付件和产物形式 |
| 报告 | `report.spec.md` | 调研分析正文 |
| 演示 | `*-slides.html` | 基于报告生成的交互式 HTML 幻灯片 |
| 索引 | `index.html` | 仅新增 slides 卡片，不索引任何非 slides 文件 |

---

## index.html 规则

- **只允许索引 HTML slides**。严禁放入 .md、.drawio、.svg、.png 等任何非 slides 格式的链接。
- 新增卡片放入合适的 section 或新建 section，保持页面结构清晰。

---

## 过程性内容禁令

最终产物（report.spec.md、*-slides.html）不得残留任何**过程性内容**。过程性内容是指任何让读者明显感觉到"该内容出过错或信息不足，而后经过修正"的叙述。

**检查关键词**（扫描全篇删除）：合并、新增泳道、重画、drawio MCP、过程、原本、此前、曾经、改为、更名、同源于、修订自、已调整、已修改。

**二次修改规则**：每次对 report 或 slides 做修正后，必须对过程性内容做一轮额外审查，确保修正痕迹完全消除。每个人看到的内容应该是最终状态，只关注内容本身。

---

## 文件精简

- 仅保留必要的 .md（req/plan/report）和 HTML slides。
- 过程性文件（审查记录、临时笔记、运行产物等）不得提交。
- `output/` 目录为 ppt-skill 运行产物，不提交（已在 .gitignore）。

---

## Git 规范

- 按任务粒度拆分 commit，一个任务一个或多个 commit。
- 多个任务完成并验证后统一 push 到远程。
- push 前必须确保：当前任务的所有阶段产物（req → plan → report → slides）都已完成。不允许存在半成品。

---

## 多视图一致性

- 架构图和时序图共用一套组件命名/配色。改一处命名必须同步检查所有相关 .drawio 和 .md 中的引用。
- .md 中的图例块与 .drawio 内 legend 单元格内容对齐。

---

## drawio 规范

- 默认用直线（去掉 `edgeStyle=orthogonalEdgeStyle` 和路由点）。仅父子/同列垂直串联保留折线。
- 四周留白：上/左 ≥ 30px，下/右 ≥ 60px。
- 导出 SVG 后验证文件头：正常以 `<svg xmlns=` 开头且 < 100KB。
- 编辑 .drawio 后必须重新加载再 export，否则导出旧内容。

---

## 验证

- 提交前运行 `git status --short` 检查变更文件列表。
- 所有 slides HTML 确认可在浏览器正常渲染。
- index.html 中不存在任何指向 .md 或其他非 slides 文件的链接。
