# 仓颉语言资料部署方案分析

> 调研时间：2026-06-12
> 调研范围：Kotlin/Android、Swift/iOS、ArkTS/HarmonyOS 竞品资料部署策略

---

## 1. 背景与问题

仓颉语言作为鸿蒙应用开发的第二门语言，其开发指南、工具链指南、标准库 API 参考等资料文档在部署发布时有三种可选方案：

| 方案 | 描述 |
|---|---|
| **A** | 全量从语言官网复制适配至鸿蒙应用开发统一官网 |
| **B** | 仅语言官网存放，鸿蒙侧仅放简介 + 链接跳转 |
| **C** | 混合：标准库 API 双站部署，非 API 内容仅语言站 + 链接 |

> **前提**：仓颉标准库 API 参考已有结论——需放在 developer.huawei.com 与 ArkTS API 参考同级。本文主要讨论**非标准库部分**（开发指南、工具链指南、实践、FAQ 等）。

---

## 2. 竞品部署模式对照

### 2.1 Kotlin on Android（Google + JetBrains）

```
kotlinlang.org（语言站）          developer.android.com（平台站）
──────────────────────────────────────────────────────────────
✅ 语言参考/学习指南               ✅ Android 专用 Kotlin 开发指南
✅ 标准库 API 参考                 ✅ Android Framework API 参考（Kotlin 视图）
✅ Kotlin Multiplatform 文档       ✅ Kotlin + Android 入门/实践
                                  ❌ 标准库 API 不重复部署
                                  → 语言基础类文档链接至 kotlinlang.org
```

**核心特征**：语言归语言站，平台归平台站，**标准库 API 不跨站重复**。

**根本原因**：Kotlin 由 JetBrains 所有，Google 无权限也无动机复制其语言级文档。这是组织边界决定的，不是产品设计选择。

### 2.2 Swift on iOS（Apple）

```
swift.org（社区站）               developer.apple.com（平台站）
──────────────────────────────────────────────────────────────
✅ 开源社区/语言演进/贡献           ✅ **Swift 语言指南**（THE primary hub）
✅ 源码、工具链下载                 ✅ **标准库 API 参考**（documentation/swift/）
                                  ✅ SwiftUI / SwiftData 等框架文档
                                  ✅ 视频课程、Sample Code、CodeLab
```

**核心特征**：Apple 同时拥有语言和平台，**developer.apple.com 是唯一主站**，swift.org 退化为社区/开源辅助站。标准库 API、语言指南全部统一在平台站。

### 2.3 ArkTS on HarmonyOS（华为现有模式）

```
无独立语言站                     developer.huawei.com（平台站）
──────────────────────────────────────────────────────────────
（ArkTS 是 TypeScript 超集，      ✅ 全部指南、API 参考、实践、FAQ
 不具备独立语言站条件）            ✅ 与 HarmonyOS 文档树天然一体化
```

---

## 3. 仓颉的独特定位

| 维度 | Kotlin | Swift | ArkTS | **仓颉** |
|---|---|---|---|---|
| 语言所有者 | JetBrains | Apple | 华为 | **华为** |
| 平台所有者 | Google | Apple | 华为 | **华为** |
| 有独立语言站 | ✅ kotlinlang.org | ✅ swift.org（社区） | ❌ | ✅ **cangjie-lang.cn** |
| 语言独立性 | 强（JVM 通用语言） | 强（Apple 全家桶） | 弱（TS 超集） | **强（独立编译型语言）** |

仓颉的处境：**所有者结构类似 Swift（同一家公司），但拥有类似 Kotlin 的独立语言站。**

---

## 4. 三种方案详细分析

### 方案 A：全量复制到平台站

> 仓颉语言相关的开发指南、工具链指南、标准库 API 参考等资料内容，从语言官网复制一份并适配放到鸿蒙应用开发的统一官网上。

| 优点 | 缺点 |
|---|---|
| 开发者一站式体验最佳 | 双站维护成本高，内容 drift 风险大 |
| 搜索引擎权重集中在 developer.huawei.com | 更新需同步两处，容易不一致 |
| 鸿蒙开发者无需跳转 | 语言站（cangjie-lang.cn）存在价值被削弱 |
| 对标 ArkTS 体验，仓颉不被视为"二等公民" | 需要建立同步机制和流程 |

**对标**：Swift/Apple 模式。但 Apple 实际上是以平台站为主、社区站为辅（并非"复制"关系，而是平台站就是主站）。如果仓颉走这条路，cangjie-lang.cn 需重新定位。

### 方案 B：仅语言站 + 链接跳转

> 仓颉语言相关的开发指南、工具链指南、标准库 API 参考等资料内容仅存在语言官网，鸿蒙应用侧官网仅放简单介绍，然后链接至仓颉语言官网。

| 优点 | 缺点 |
|---|---|
| 单一事实来源，零维护 drift | 开发者体验割裂——ArkTS 和仓颉之间频繁跳站 |
| 语言站地位清晰 | 仓颉在鸿蒙生态中被感知为"二等公民" |
| 无需同步工作 | 鸿蒙站内搜索无法检索仓颉内容 |
| | 与标准库 API 已定位于平台站的决策不一致 |

**对标**：Kotlin/Android 模式。但 Kotlin/Android 的分立是**跨公司组织边界**导致的，仓颉/鸿蒙是**同一家公司**，没有这个边界。

### 方案 C：混合方案——API 双站、非 API 留语言站

> 标准库 API 在语言官网和鸿蒙应用官网都放一份；开发指南、工具链指南等仅在语言官网，鸿蒙侧放链接。

| 优点 | 缺点 |
|---|---|
| API 参考与 ArkTS API 同站，查阅体验好 | 非 API 内容仍需跳站，体验不完全统一 |
| 语言指南保持单源 | 标准库 API 需同步维护两处 |
| 减少（但未消除）同步成本 | 方案逻辑不纯粹——"为什么 API 可以双份、指南不行？" |

---

## 5. 推荐方案

### 推荐：方案 A 的变体——**"平台站为主站，语言站为辅助站"**

对标 **Swift/Apple 模式**：

| 内容类型 | developer.huawei.com（主站） | cangjie-lang.cn（辅助站） |
|---|---|---|
| 开发指南（入门/开发/工具） | ✅ **主站，完整内容** | 保留，标注"最新内容见 developer.huawei.com" |
| 标准库 API 参考 | ✅ 与 ArkTS API 同级 | 保留或重定向至平台站 |
| 实践/最佳实践 | ✅ | 可选保留 |
| FAQ | ✅ | 可选保留 |
| 语言规范/设计文档 | 链接至语言站 | ✅ **主站** |
| 工具链源码/构建 | 链接至语言站 | ✅ **主站** |
| 社区/贡献/开源 | 链接至语言站 | ✅ **主站** |

### 依据

1. **Swift 是唯一可类比先例**：同一家公司拥有语言和平台，且语言有独立社区站。Apple 选择 developer.apple.com 做主站，swift.org 做开源社区站。仓颉应走同一条路。

2. **Kotlin 模式不适用**：Kotlin/Android 的分立是组织边界导致的（JetBrains ≠ Google），不是产品设计选择。仓颉/鸿蒙没有这个边界。

3. **开发者期望**：鸿蒙开发者已习惯在 developer.huawei.com 找到所有 ArkTS 资料。如果仓颉资料不在同一站，会被感知为"二等公民"，不利于推广。

4. **API 参考必须在平台站**（已有结论）：既然最核心的 API 参考已在平台站，把指南也放过来是自然延伸——否则开发者看着 API 却找不到"怎么用"的指南，体验断裂。

5. **语言站的保留价值**：cangjie-lang.cn 应转型为**语言开源社区站**（对标 swift.org），承载语言规范、编译器源码、社区贡献、工具链下载——即"语言本身"的内容，而非"用仓颉开发鸿蒙应用"的教程。

---

## 6. 落地建议

| 阶段 | 动作 |
|---|---|
| **短期** | developer.huawei.com 仓颉专区已基本建成，继续按 ArkTS 对标充实内容深度 |
| **中期** | cangjie-lang.cn 逐步转型：指南类内容加"最新版见 developer.huawei.com"提示；强化语言规范/工具链/社区内容 |
| **长期** | 形成稳定分工：developer.huawei.com = 用仓颉开发鸿蒙；cangjie-lang.cn = 仓颉语言本身 |

---

## 7. 竞品资料快速索引

| 竞品 | 语言站 | 平台站 | 标准库 API 位置 | 模式 |
|---|---|---|---|---|
| Kotlin / Android | [kotlinlang.org](https://kotlinlang.org/docs/home.html) | [developer.android.com/kotlin](https://developer.android.com/kotlin) | kotlinlang.org（不重复） | 分站 + 链接 |
| Swift / iOS | [swift.org](https://www.swift.org/) | [developer.apple.com/swift](https://developer.apple.com/swift/) | developer.apple.com | 平台主站 |
| ArkTS / HarmonyOS | — | [developer.huawei.com](https://developer.huawei.com) | developer.huawei.com | 统一平台站 |

---

> **核心结论**：仓颉应走 Swift/Apple 路线——开发者统一入口在 developer.huawei.com，cangjie-lang.cn 转型为语言开源社区站。不推荐 Kotlin/Google 的"分站链接"模式，因为那反映的是跨公司组织边界而非产品设计选择。
