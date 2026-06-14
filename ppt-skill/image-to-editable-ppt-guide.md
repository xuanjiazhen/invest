# Image to Editable PPT Skill — 小白入门指南

> 适用人群：首次接触该 skill 的开发者，希望快速了解安装、使用和注意事项。

---

## Part 1：安装与使用

### 1.1 Codex 环境（推荐）

**安装**：

```
/install image-to-editable-ppt
```

或从 GitHub 安装：

```
安装 image-to-editable-ppt 这个 skill，地址是 https://github.com/ningzimu/image-to-editable-ppt-skill
```

**使用**：

```
$image-to-editable-ppt 把这张图片转成可编辑 PPT。
$image-to-editable-ppt 把这些图片转成一个可编辑 PPT。
$image-to-editable-ppt 把 /path/to/deck.pdf 转成可编辑 PPT。
$image-to-editable-ppt 把 /path/to/image-based.pptx 转成可编辑 PPT。
```

直接将图片粘贴或附加到对话框，或提供本地文件路径即可。

### 1.2 Claude Code 环境

在 Claude Code 中安装该 skill 后，通过自然语言触发：

```
帮我把这张截图转成可编辑的 PPT
```

Claude Code 会自动识别并调用 skill。

### 1.3 其他支持 Skill 的 Agent 平台

任何支持 skill 加载、文件读写、CLI 执行和 subagent/page worker 分派的 agent 平台均可使用。安装方式参照各平台的 skill 安装文档。

### 1.4 文字校正 OCR Token 配置（推荐）

Skill 通过百度 AI Studio 的 PaddleOCR-VL 服务校正文字大小和位置。配置步骤：

1. 访问 [百度 AI Studio](https://aistudio.baidu.com/account/accessToken) 申请 Access Token
2. 个人用户免费额度完全够用，无额外费用
3. 首次使用时 AI 会主动询问 Token，发送给 AI 即可
4. AI 代劳写入 `~/.editppt/config.yaml`（Windows：`%USERPROFILE%\.editppt\config.yaml`），一次配置长期生效

不提供 Token 也能运行——skill 退化为内置离线检测器（知道文字在哪、多大，但不识别内容），文字还原质量有折扣。

### 1.5 图片 Backend 与第三方 API 配置

`editppt image` 自动选择图片后端：优先本机 Codex OAuth；不可用时读取 `~/.editppt/config.yaml` 中的 OpenAI-compatible API 配置。

通常不需要手动配置。仅在以下情况需要：
- 在非 Codex 环境中使用且无 Codex OAuth
- `editppt image` 报告所有 backend 都不可用

配置方式：告诉 AI 你要用的服务、base URL、模型名和 API key。AI 自动写入配置并在输出中遮蔽敏感值。**不要把 API key 写进项目目录。**

---

## Part 2：技能能力

### 2.1 输入类型

| 输入 | 输出 |
|------|------|
| 1 张图片 | 1 页 .pptx |
| 多张图片 | 多页 .pptx，按提供顺序排列 |
| 多页 PDF | 多页 .pptx，PDF 第 N 页 → 输出第 N 页 |
| 图片版 PPTX | 页数一致的 .pptx，原第 N 页 → 输出第 N 页 |

### 2.2 输出能力

- **文本 → 原生文本框**：可编辑、可调整字体/大小/颜色
- **简单几何 → PowerPoint 形状**：矩形、圆形、线条等原生形状，可调整
- **复杂视觉 → 独立图片资产**：照片、插画、纹理等保留为可移动图片
- **多页并行处理**：按 `max_concurrent_pages` 并发分派给 page worker

### 2.3 文字测量驱动

文字大小与位置由 OCR 测量数据驱动：
- 为每页生成文字标注（框坐标 + 字号 + 字号分组）
- AI 按测量值还原文字，同级文字字号自动保持一致
- 不再依赖目测

### 2.4 页面备注保留

.pptx 输入的页面备注会原样复制到输出对应页（不翻译、不摘要、不改写）。

### 2.5 工作流程

```
输入归一化 → 逐页分派 page worker → 每页重建+自检+修正 → 组装最终 .pptx → 校验
```

---

## Part 3：注意事项

### 3.1 模型选择

| 模型 | 表现 |
|------|------|
| GPT-5.5（ChatGPT Pro） | 表现较好，流程控制稳定。**推荐** |
| GPT-5（ChatGPT Plus） | 可用但 token 消耗偏高，**谨慎使用** |
| DeepSeek | **不支持识图**，中间步骤（源图+标注信息→JSON）会直接编造内容，**不要尝试**。等 DeepSeek 支持识图后可能改善 |
| GPT-5.5 以下 | 不保证效果 |

### 3.2 Token 消耗

- 本 skill 流程控制复杂，token 花费较高
- 将一个图片 PPT 转成可编辑 PPT 的成本约为生成图片 PPT 的 2-3 倍
- 10 页 PPT 可能耗尽 ChatGPT Plus 的 5 小时额度
- 单页复原时间 >10 分钟
- **如果没有强烈的可编辑需求，不要使用这个 skill**

### 3.3 轻量替代

如果只是对某一页 PPT 图片不满意、想局部修改：直接用 gpt-image-2 的图像编辑能力，把图片发给它针对性修改即可。这比走完整 skill 流程轻量得多。

### 3.4 能力边界

- 视觉相似 ≠ 可编辑：最终判断应同时看 PPTX 结构、文本覆盖、资产来源
- 文字位置可能有轻微偏移，不能保证 100% 复刻原始页面
- 照片、插画、纹理、手绘装饰等复杂视觉元素只能作为独立图片资产移动，内部不可编辑
- 表格、图表、流程图等结构化区域优先保留可编辑语义，低置信度时保留为资产
- 本 skill 面向**已有图片/PDF → 可编辑 PPT 重建**，不是从零生成 PPT（生成 PPT 请用 codex-ppt-skill）

### 3.5 运行要求

- 多页输入需要 agent 支持 page worker/subagent 分派机制
- 需要可用 `editppt image` backend（Codex OAuth 或第三方 API）
- OCR Token 配置为可选项但强烈推荐

---

## 参考链接

- [Skill 仓库](https://github.com/ningzimu/image-to-editable-ppt-skill)
- [Skill 设计与调优经验文章](https://mp.weixin.qq.com/s/LaxWBX-nogHPpSxlk-Vs8Q)
- [Codex PPT Skill（生成 PPT 用）](https://github.com/ningzimu/codex-ppt-skill)
