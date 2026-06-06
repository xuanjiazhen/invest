# 鸿蒙 ArkTS 与仓颉检查能力对比调研报告

更新时间：2026-06-05  
调研对象：ArkTS / HarmonyOS 应用开发检查能力、仓颉语言与 cjlint 检查能力  
输出口径：按“语言本身”和“应用框架相关”两大类对比，并列出承载能力的工具。

## 1. 结论摘要

ArkTS 与仓颉的检查能力不是同一层面的简单替代关系。

ArkTS 侧的能力由多种工具共同承载：编译器与编辑器实时检查负责语法/语义和严格类型反馈，Code Linter/codelinter 负责 TS/ArkTS 规范、ArkUI 性能、多端体验、API 兼容性、HarmonyOS 正确性规则，HiChecker 负责开发期运行检测。其优势集中在应用框架、ArkUI、HarmonyOS API、多端适配和性能调优。

仓颉侧的能力由编译器和 cjlint 承载。编译器提供静态强类型、语法语义、模块编译等基础检查；cjlint 基于仓颉语言编程规范，覆盖命名、格式、函数、接口、表达式、错误处理、包导入、并发、安全、序列化、文件与资源治理、语法禁用和告警屏蔽。其优势集中在语言本身的 Clean Source 规范、安全编码、并发规则和可配置语言子集约束。

本报告将 HiChecker 纳入主体，但明确其不是编译期静态检查，而是开发期运行检测/问题发现能力。它用于补足 ArkTS 应用框架问题发现闭环，不参与“纯静态检查”强弱判断。

## 2. 工具承载关系

| 语言/生态 | 工具 | 类型 | 承载的主要检查能力 |
|---|---|---|---|
| ArkTS | ArkTS 编译器 / DevEco Studio 实时检查 | 编译期/编辑期 | 语法语义、严格类型检查、编译错误、实时错误/警告提示 |
| ArkTS | Code Linter | IDE 静态检查 | TS/ArkTS 编程规范、最佳实践、安全、性能、预览、多端、风格、正确性、兼容性 |
| ArkTS | codelinter | 命令行静态检查 | 与 Code Linter 同源的命令行检查、CI 门禁、输出报告、QuickFix、增量检查 |
| ArkTS | HiChecker | 开发期运行检测 | 耗时函数调用、Ability 连接泄漏、ArkUI 性能问题，通过日志或 crash 暴露问题 |
| 仓颉 | cjc 编译器 | 编译期 | 语法语义、静态类型、模块编译、基础语言约束 |
| 仓颉 | cjlint | 命令行静态检查 | Clean Source 规范、命名/格式、函数/接口/表达式、并发、安全、序列化、语法禁用、告警屏蔽 |

## 3. 总览矩阵

| 能力项 | 大类 | ArkTS 支持状态 | ArkTS 承载工具 | 仓颉支持状态 | 仓颉承载工具 | 差异结论 |
|---|---|---|---|---|---|---|
| 语法语义与类型检查 | 语言本身 | 支持 | ArkTS 编译器、DevEco Studio 实时检查 | 支持 | cjc 编译器 | 两侧都有基础编译期能力；仓颉静态强类型是语言底座，ArkTS 另有严格类型实时检查。 |
| 显式类型与 any 风险 | 语言本身 | 支持 | Code Linter、codelinter | 部分支持 | cjc 编译器、cjlint | ArkTS 对 any 风险有专门规则；仓颉通过静态强类型和 public 类型声明规则间接覆盖。 |
| 命名与文件命名 | 语言本身 | 支持 | Code Linter、codelinter | 支持 | cjlint | 两侧都支持；ArkTS 使用 ESLint 风格规则，仓颉使用 G.NAM 规范。 |
| 格式与代码风格 | 语言本身 | 支持 | Code Linter、codelinter | 支持 | cjlint、格式化工具 | 两侧都有；ArkTS 风格规则更细，仓颉 cjlint 默认检查 UTF-8 并通过语言规范约束。 |
| 代码坏味道 | 语言本身 | 支持 | Code Linter、codelinter | 支持 | cjlint | 两侧都覆盖未使用参数、函数职责、表达式可读性等，仓颉默认规则更集中列出。 |
| 表达式/函数/接口规范 | 语言本身 | 支持 | Code Linter、codelinter | 支持 | cjlint | 仓颉在函数、接口、操作符、表达式上有明确 G.FUN/G.ITF/G.OPR/G.EXP 规则；ArkTS 主要依赖 TypeScript/ArkTS 规则和自定义 selector。 |
| 安全编码 | 语言本身 | 支持 | Code Linter、codelinter | 支持 | cjlint | ArkTS 强在不安全加密算法；仓颉强在信任边界、日志敏感信息、硬编码、序列化安全。 |
| 并发/锁/数据竞争 | 语言本身 | 弱/部分 | ArkTS 编译器、项目自定义规则 | 支持 | cjlint | 仓颉有 G.CON、P.01、P.02；ArkTS 已取证规则中没有同粒度默认并发规则。 |
| 禁用语法/语言子集约束 | 语言本身 | 部分支持 | Code Linter 自定义规则 | 支持 | cjlint | ArkTS 可用 no-restricted-syntax 自定义；仓颉 G.SYN.01 开箱支持禁用语法表。 |
| 配置、屏蔽与 CI 门禁 | 语言本身 | 支持 | codelinter、Code Linter | 支持 | cjlint | 两侧均支持规则配置和屏蔽；ArkTS 额外支持 QuickFix、增量检查、退出码门禁。 |
| ArkUI 性能调优 | 应用框架相关 | 支持 | Code Linter、codelinter、HiChecker | 不支持/未取证 | 无对应公开 cjlint 规则 | ArkTS 明显优势，覆盖组件复用、状态变量、动画、图片、Web、DataShare 等。 |
| HarmonyOS API 兼容性 | 应用框架相关 | 支持 | Code Linter、codelinter | 不支持/未取证 | 无对应公开 cjlint 规则 | ArkTS 有 @compatibility/api-compatibility-check；仓颉公开 cjlint 不覆盖 HarmonyOS API 兼容规则。 |
| HarmonyOS 正确性 | 应用框架相关 | 支持 | Code Linter、codelinter | 不支持/未取证 | 无对应公开 cjlint 规则 | ArkTS 覆盖媒体、网络、依赖、状态模型等 HarmonyOS 场景。 |
| 一次开发多端部署 | 应用框架相关 | 支持 | Code Linter、codelinter | 不支持/未取证 | 无对应公开 cjlint 规则 | ArkTS 有颜色、字号、单位、栅格、热区、断点等多端规则。 |
| 预览能力约束 | 应用框架相关 | 支持 | Code Linter、codelinter | 不适用 | 无 | ArkTS 针对 @Preview/@Entry/页面方法有专门规则，仓颉语言工具不涉及。 |
| 开发期运行检测 | 应用框架相关 | 支持 | HiChecker | 不支持/不适用 | 无 | HiChecker 可检测耗时调用、Ability 泄漏、ArkUI 性能，但不是编译期静态检查。 |

## 4. 语言本身能力对比

### 4.1 类型系统与显式类型

ArkTS 通过编译器和实时检查提供语法、语义、严格类型反馈；Code Linter 进一步提供 `@typescript-eslint/no-explicit-any`、`no-unsafe-argument`、`no-unsafe-assignment`、`no-unsafe-call`、`no-unsafe-member-access`、`no-unsafe-return`、`explicit-function-return-type`、`explicit-module-boundary-types` 等规则，核心目标是减少 `any`、不安全边界和隐式类型造成的维护风险。

仓颉由 cjc 编译器承担静态强类型基础检查，cjlint 在规范层补充 public 变量、public 函数返回类型、接口使用、泛型约束等规范。它不需要检查 `any`，但会通过语言类型系统和规范规则控制接口边界。

### 4.2 命名、格式与代码风格

ArkTS 的承载工具是 Code Linter/codelinter，典型规则包括 `@typescript-eslint/naming-convention` 和 `@hw-stylistic/file-naming-convention`，以及缩进、括号、逗号空格、关键字空格、行宽、引号、分号间距等 `@hw-stylistic/*` 规则。

仓颉的承载工具是 cjlint，默认启用 `G.NAM.01` 到 `G.NAM.05`：包名、源文件名、类型名、函数名、全局/static let 变量命名；`G.FMT.01` 检查源文件编码必须为 UTF-8。

### 4.3 代码坏味道、函数和表达式

ArkTS 侧可通过 TypeScript ESLint 规则、ArkTS 风格规则和 AST selector 自定义规则检查坏味道。例如禁止特定调用、约束命名、限制不安全类型、限制动态 delete、禁止 for-in 遍历数组等。

仓颉侧 cjlint 默认规则更集中：`G.FUN.01` 要求函数功能单一，`G.FUN.02` 禁止未使用参数，`G.EXP.01` 到 `G.EXP.07` 覆盖 match pattern 混用、浮点比较、短路表达式右侧副作用、表达式优先级、Bool 比较冗余、左右表达式稳定性等。

### 4.4 安全编码

ArkTS 的安全规则主要由 `@security/*` 承载，重点包括不安全加密算法与模式：AES ECB、不安全 DH/DSA/RSA/3DES、弱哈希、弱 MAC、注释遗留代码等。

仓颉 cjlint 默认安全规则覆盖更广的通用安全编程主题：`G.CHK.01` 跨信任边界数据使用前校验，`G.CHK.02` 禁止直接使用外部数据记录日志，`G.CHK.04` 禁止直接使用不可信数据构造正则表达式，`G.ERR.02` 防止异常泄露敏感信息，`G.SER.01` 到 `G.SER.03` 覆盖序列化安全，`G.OTH.01` 到 `G.OTH.04` 覆盖日志敏感信息、硬编码、公网地址、敏感数据清零。

### 4.5 并发、锁与数据竞争

ArkTS 已取证的默认 Code Linter 规则中没有与仓颉同粒度的并发/锁/数据竞争规则。可通过编译器、项目自定义规则、运行期监控或其他工程手段补足。

仓颉 cjlint 默认支持 `G.CON.01` 禁止将系统内部锁对象暴露给不可信代码，`G.CON.02` 异常路径释放已持有锁，`G.CON.03` 禁止用非线程安全函数覆写线程安全函数，`P.01` 统一锁请求顺序避免死锁，`P.02` 避免数据竞争。

### 4.6 禁用语法与架构约束

ArkTS 可以通过 `@typescript-eslint/no-restricted-syntax` 和自定义 AST selector 禁止某类语法或调用。优点是灵活，适合项目级规则；缺点是需要团队自行定义规则和 selector。

仓颉 cjlint 的 `G.SYN.01` 支持配置禁用语法，关键字包括 Import、Let、Spawn、Synchronized、Main、MacroQuote、Foreign、While、Extend、Type、Operator、GlobalVariable、Enum、Class、Interface、Struct、Generic、When、Differentiable、Match、TryCatch、HigherOrderFunc、PrimitiveType、ContainerType。它更适合统一语言子集和架构约束。

### 4.7 配置、屏蔽与 CI

ArkTS codelinter 支持 `--config/-c` 指定配置、`--fix` 自动修复、`--format/-f` 输出 default/json/xml/html、`--output/-o` 保存结果、`--incremental/-i` 检查 Git 增量文件、`--exit-on/-e` 按 error/warn/suggestion 产生非零退出码。IDE 中还支持 Ignore、eslint-disable 注释、导出 Excel。

仓颉 cjlint 支持 `-f` 指定源码目录、`-e` 排除文件/目录、`-o` 输出路径、`-r` 输出 json/csv、`-c` 指定 config、`-m` 指定 modules。屏蔽机制包括 `cjlint_rule_list.json` 规则级启停、`exclude_lists.json` 精确屏蔽、`cjlint-ignore` 注释屏蔽、`-e` 或 `cjlint_file_exclude.cfg` 文件级屏蔽。

## 5. 应用框架相关能力对比

### 5.1 ArkUI 性能调优

承载工具：ArkTS Code Linter、codelinter、HiChecker。

Code Linter 的 `@performance/*` 规则覆盖 ArkUI 和应用性能场景，包括 ForEach keyGenerator、高频 Hilog、export *、aboutToReuse 状态变量更新、animateTo 合并、按需加载、复用组件函数入参、循环读取状态变量、LazyForEach keyGenerator 中 stringify、Grid cacheCount、AVPlayer 实例缓存、EffectKit blur、GridLayoutOptions、用临时变量替代状态变量、用 @ObjectLink 替代 @Prop、Swiper 预加载、组件复用、transition 替代 animateTo、锁最高帧率、启动图标分辨率、WaterFlow 预加载、Web 预渲染停止渲染、GIF 硬解码、按需 import、深拷贝、Date 实例复用、系统原生加密替换、ImageAnimation 不可见区域监听、DataShare 查询结果释放等。

仓颉公开 cjlint 规则没有同类 HarmonyOS/ArkUI 性能规则。它只能通过通用语言规则间接改善代码质量，例如不可变变量、缩小副作用、并发安全、表达式规范。

### 5.2 HarmonyOS 正确性与兼容性

承载工具：ArkTS Code Linter、codelinter。

`@correctness/*` 规则覆盖 AVSession 按钮、音频中断、暂停/静音、AVSession 元数据、图像像素格式、图像插值、默认网络变化监听、多网络并发监听、ImageReceiver stride、冗余依赖、V1 状态对象嵌套属性更新格式、状态对象成员作为函数参数等。

`@compatibility/api-compatibility-check` 用于 API 兼容性检查，帮助识别 SDK/API 使用边界。

仓颉公开 cjlint 规则没有同类 HarmonyOS API 兼容性或媒体/网络框架正确性规则。

### 5.3 一次开发多端部署

承载工具：ArkTS Code Linter、codelinter。

`@cross-device-app-dev/*` 覆盖文本与背景颜色对比度、颜色资源引用、字体大小与单位、栅格列/偏移、侧边导航、通用尺寸单位、触摸热区、系统断点判断、窗口尺寸变化监听、沉浸式效果等。这些规则直接面向 HarmonyOS 多设备体验。

仓颉公开 cjlint 规则不涉及 UI 多端体验。

### 5.4 预览约束

承载工具：ArkTS Code Linter、codelinter。

`@previewer/*` 规则覆盖本地初始化默认值、非路由组件禁止页面级方法、@Entry/@Preview 组件装饰器使用约束等，保障 DevEco Studio 预览体验和组件预览可用性。

仓颉语言工具不涉及 ArkUI 预览。

### 5.5 HiChecker 开发期运行检测

承载工具：HiChecker。

HiChecker 可作为应用开发阶段的检测能力，用于检测运行过程中容易忽略的问题。规则常量包括 `RULE_THREAD_CHECK_SLOW_PROCESS` 耗时函数调用、`RULE_CHECK_ABILITY_CONNECTION_LEAK` Ability 连接泄漏、`RULE_CHECK_ARKUI_PERFORMANCE` ArkUI 性能，告警行为包括记录日志和触发 crash。它不属于编译期静态检查，但可补足应用框架问题发现闭环。

## 6. 差异项详解

### 差异项 1：ArkTS 的应用框架检查显著强于仓颉公开 cjlint

| 子类 | 做什么 | 为什么重要 | ArkTS 工具 | 仓颉近似能力 |
|---|---|---|---|---|
| ArkUI 性能 | 检查状态变量、组件复用、动画、图片、Web、DataShare 等性能风险 | 这些问题会直接影响首帧、滑动、动效和资源占用 | Code Linter、codelinter、HiChecker | 无直接公开规则；仅能由通用语言规范间接约束 |
| HarmonyOS 正确性 | 检查音频、媒体、网络监听、状态模型、依赖等使用方式 | 避免 API 使用不当导致功能异常或资源问题 | Code Linter、codelinter | 无直接公开规则 |
| API 兼容性 | 检查 API 使用与目标 SDK/平台兼容性 | 降低升级 SDK 和多版本运行风险 | Code Linter、codelinter | 无直接公开规则 |
| 多端体验 | 检查字号、颜色、单位、栅格、热区、断点等 | 保证一次开发多端部署体验一致 | Code Linter、codelinter | 无直接公开规则 |
| 预览能力 | 检查 @Preview/@Entry 和页面级方法使用限制 | 保证组件预览稳定、默认值可用 | Code Linter、codelinter | 不适用 |

### 差异项 2：仓颉的并发/锁/数据竞争规则强于 ArkTS 已取证默认规则

| 子类 | 做什么 | 为什么重要 | 仓颉工具 | ArkTS 近似能力 |
|---|---|---|---|---|
| 锁对象暴露 | 禁止将内部锁对象暴露给不可信代码 | 防止外部代码破坏同步边界 | cjlint `G.CON.01` | 无同粒度默认规则 |
| 异常路径释放锁 | 确保异常场景释放已持有锁 | 防止死锁和资源长期占用 | cjlint `G.CON.02` | 可依赖代码审查/自定义规则 |
| 线程安全覆写 | 禁止非线程安全函数覆写线程安全函数 | 防止继承/多态破坏并发语义 | cjlint `G.CON.03` | 无同粒度默认规则 |
| 锁顺序 | 使用相同顺序请求锁 | 避免循环等待导致死锁 | cjlint `P.01` | 无同粒度默认规则 |
| 数据竞争 | 避免 data race | 保障并发结果确定性 | cjlint `P.02` | 可由语言/运行期工具间接发现 |

### 差异项 3：ArkTS 的加密算法检查与仓颉的通用安全规范侧重点不同

| 子类 | 做什么 | 为什么重要 | ArkTS 工具 | 仓颉工具 |
|---|---|---|---|---|
| 不安全算法/模式 | 禁止 AES ECB、弱 DH/DSA/RSA/3DES、弱 hash/MAC | 防止误用弱密码算法 | Code Linter `@security/*` | 公开 cjlint 默认规则未以算法族为主 |
| 信任边界输入 | 使用跨信任边界数据前必须校验 | 防止注入和异常输入传播 | 可自定义规则 | cjlint `G.CHK.01` |
| 日志敏感信息 | 禁止外部数据和敏感数据直接进日志 | 防止凭据、密钥、隐私泄露 | Code Linter 部分覆盖，高频日志性能规则 | cjlint `G.CHK.02`、`G.OTH.01` |
| 硬编码敏感信息 | 禁止口令、密钥等硬编码 | 降低泄漏和凭据复用风险 | 可自定义规则 | cjlint `G.OTH.02` |
| 序列化安全 | 检查敏感数据加密、反序列化绕过、类型一致性 | 防止序列化攻击和敏感数据泄露 | 已取证规则未见专门族 | cjlint `G.SER.01~03` |

### 差异项 4：仓颉的禁用语法更适合作为语言子集治理

| 子类 | 做什么 | 为什么重要 | 仓颉工具 | ArkTS 近似能力 |
|---|---|---|---|---|
| 禁止导入/跨语言/宏 | 限制 Import、Foreign、MacroQuote 等 | 控制依赖和互操作边界 | cjlint `G.SYN.01` | no-restricted-syntax 可自定义 |
| 禁止线程/同步/while | 限制 Spawn、Synchronized、While | 防止复杂并发和死循环 | cjlint `G.SYN.01` | 可自定义 |
| 禁止复杂类型系统特性 | 限制 Class、Interface、Struct、Generic、Enum、Match 等 | 统一团队可接受语言子集 | cjlint `G.SYN.01` | 可自定义 |
| 禁止全局变量/操作符重载 | 限制 GlobalVariable、Operator | 减少副作用和可读性风险 | cjlint `G.SYN.01` | 可自定义 |

### 差异项 5：ArkTS 工程化检查链路更完整

| 子类 | 做什么 | 为什么重要 | ArkTS 工具 | 仓颉近似能力 |
|---|---|---|---|---|
| IDE 实时检查 | 编辑时显示错误/警告并支持快速修复 | 缩短问题发现周期 | DevEco Studio 实时检查、Code Linter | 仓颉 IDE 授权页未取证，公开 cjlint 偏命令行 |
| 自动修复 | 对部分规则执行 QuickFix | 降低修复成本 | Code Linter、codelinter `--fix` | 公开 cjlint 未见自动修复 |
| 增量检查 | 只检查 Git 新增/修改/重命名文件 | 提升提交前门禁效率 | codelinter `--incremental` | 公开 cjlint 未见 Git 增量能力 |
| 退出码门禁 | 按 error/warn/suggestion 产生非零退出码 | 易接入 CI 阻断 | codelinter `--exit-on` | 可解析 json/csv 报告间接实现 |
| 报告导出 | 输出 json/xml/html/Excel 等 | 支撑审计和趋势分析 | codelinter、Code Linter | cjlint json/csv |

## 7. 华为风格 PPT 制作要点

参考《华为算力平台汇报提纲 2024》与浅色版 16:9 模板，可总结如下制作要点：

1. 使用 16:9 宽屏，浅色背景，红、黑、灰为主色，红色用于强调主线和关键结论。
2. 页脚稳定呈现密级/页码等信息，形成正式汇报材料感。
3. 先给说明、版本、编写人、内容框架，再展开章节，适合组织级材料复用和定向裁剪。
4. 标题通常是结论或定义句，而不是泛泛主题；每页围绕一个主结论组织信息。
5. 内容密度较高，但通过分区、表格、流程、分层图、时间轴和矩阵保持可扫描。
6. 大量使用“框架页”和“章节页”帮助听众建立结构：例如内容框架、趋势/实践/方案/创新等模块。
7. 技术内容倾向于用分层架构、能力地图、矩阵、案例收益、流程图表达，而不是大段正文。
8. 图形语言克制：少用装饰，更多使用红色强调线、灰色分隔、浅色底框和明确的左右/上下分区。
9. 适合本次 PPT 的应用方式：封面和结束页使用模板，主体使用矩阵、双栏对比、分层工具链、差异拆解图和落地建议页；避免网页式卡片堆叠。

## 8. 来源与边界

### 8.1 ArkTS / HarmonyOS

- 华为开发者文档：代码检查入口 `https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-code-check`
- 华为开发者文档：代码实时检查及快速修复 `https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-realtime-check`
- 华为开发者文档：Code Linter 代码检查 `https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-code-linter`
- 华为开发者文档：Code Linter 规则清单 `https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-codelinter-rule`
- 华为开发者文档：recommended 推荐规则清单 `https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-coderlinter-recommended-rules`
- 华为开发者文档：codelinter 命令行 `https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-command-line-codelinter`
- 华为开发者文档：HiChecker ArkTS 指南 `https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/hichecker-guidelines-arkts`
- 华为开发者文档：HiChecker API `https://developer.huawei.com/consumer/cn/doc/harmonyos-references/js-apis-hichecker`

### 8.2 仓颉

- 仓颉公开文档：静态检查工具 `https://docs.cangjie-lang.cn/cjnative/user_manual/tools/source_zh_cn/tools/cjlint_manual_community.html`
- GitCode：Cangjie/cangjie_tools cjlint 开发指南 `https://gitcode.com/Cangjie/cangjie_tools/blob/main/cjlint/doc/developer_guide_zh.md`
- 华为开发者联盟仓颉页面 `https://developer.huawei.com/consumer/cn/doc/cangjie-guides/cj-cjlint_manual` 在当前会话显示“需授权账号查阅”，未能读取授权正文。因此仓颉结论以公开仓颉文档和开源工具文档为证据，授权文档中若有 DevEco Studio 集成或 HarmonyOS 适配规则，需要后续补证。

### 8.3 口径限制

1. “支持”表示已在公开或可访问文档中找到明确能力或规则承载工具。
2. “部分支持”表示能力可通过近似工具或自定义规则实现，但缺少同粒度默认规则。
3. “不支持/未取证”表示公开文档未见对应能力，不代表产品一定没有内部或授权能力。
4. HiChecker 虽纳入应用框架相关主体，但它是开发期运行检测能力，不是编译期静态检查。
