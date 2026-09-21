# WWDC 2026 苹果语言、编译器、工具链与 Xcode 更新调研

## 2. 给仓颉专家的 Swift 最小背景

| 概念 | 在本次分享中的含义 | 容易产生的误解 |
|---|---|---|
| 值语义与引用语义 | struct 常用于值；class 是引用对象；性能讨论同时涉及数据复制与引用计数 | 值语义不表示每次赋值必然发生物理内存复制 |
| ARC 与写时复制 | ARC 管理引用对象；写时复制可让值共享底层存储，修改时必要才分离 | 共享存储不意味着后续修改没有成本 |
| protocol / 泛型 | protocol 描述能力；泛型让算法适配不同具体类型 | protocol 值与泛型参数不具有完全相同的优化条件 |
| `some P` / `any P` | 前者隐藏但保持一个具体类型；后者用于存在类型抽象 | 两者不是简单的可互换缩写 |
| `~Copyable` | 放宽隐含的可复制要求；具体类型可不支持复制 | 泛型上的 `~Copyable` 不要求所有实参都不可复制 |
| `~Escapable` | 值的有效期受到生命周期依赖约束 | 不是“永远不能从任何函数返回”；返回是否允许取决于依赖关系 |
| borrowing / inout | 分别提供临时共享读取、临时独占修改的访问约定 | 借用不是拥有一份独立副本 |
| Task / actor / executor | Task 是异步工作；actor 约束隔离访问；executor 执行任务片段 | `async` 不等于后台线程，更不保证并行 |
| SwiftPM / Swift Build | 前者管理包和构建入口，后者是构建执行系统 | 构建系统不是 Swift 优化器，也不是包仓库 |
| Xcode / LLDB / Instruments | IDE 集成、交互调试、性能观测分别承担不同职责 | IDE 提供可视化不等于其余组件只能在 IDE 中使用 |

上述背景只用于建立阅读模型。非复制类型及借用约定可追溯 SE-0390；异步函数与潜在挂起点见 SE-0296；存在类型与不透明返回类型的区别可结合 SE-0244 阅读。它们是历史基础，不是 WWDC26 首次引入。[^s3][^s4][^s5]



| 领域 | 本轮重点 | 归属/证据边界 | 专家应关注的问题 |
|---|---|---|---|
| 日常语言体验 | anyAppleOS、局部警告策略、异步 defer | 6.4 指南；具体语义看提案 | 如何降低渐进迁移成本？ |
| 安全高性能 | 借用访问器、Iterable、Ref、独占容器 | SE-0516 与 SE-0527 现标注 Swift 6.4 已实现；具体 SDK 仍须固定版本核验 | 安全约束怎样穿过抽象边界？ |
| 优化控制 | 强制内联、显式特化 | 6.3 已有，WWDC26 再介绍 | 怎样提供可预测性而不失去优化自由？ |
| 编译性能 | 类型求解剪枝、依赖扫描去重 | 前者是大会前维护者说明，后者是 Xcode 27 说明 | 是减少工作量，还是只减少单步开销？ |
| 构建与工具链 | Swift Build 统一后端、工具链管理 | SwiftPM 6.3 预览、6.4 正式默认 | IDE 与 CLI 能否消费同一份构建语义？ |
| 互操作 | C 导出、安全 Span 包装、Java/Android | C 导出 6.3 已发布；安全包装按具体形式分级 | ABI 与安全契约能否分别演进？ |
| Xcode | Agent 工作流、Device Hub、测试及诊断 | Xcode 27；Agent 初次引入为 26.3 | 生成速度提升之后，验证如何跟上？ |

该表是索引；精确来源与限制在下节逐项列出，不把全表视为“6.4 全新且完全稳定的能力清单”。

## 4. 语言：把迁移与正确性做进表达方式

### 4.1 anyAppleOS：公共默认与平台例外

**事实。** Swift 6.4 指南介绍 `anyAppleOS`，用于简化 Apple 平台可用性表达。[^s6]



### 4.2 在源码中控制编译器警告（SE-0522）

**事实。** SE-0522 标注 Swift 6.4 已实现。声明上的 `@diagnose` 可将指定诊断组中的警告设为 `error`、`warning` 或 `ignored`，覆盖声明签名及其词法作用域；`reason` 是可选的理由字符串。固有的语法、类型等编译错误不能通过它降级。内层声明可覆盖外层策略；模块若采用 `-suppress-warnings`，这些属性不再改变警告行为。[^s7]



### 4.3 在 defer 体中支持异步调用（SE-0493）

**事实。** SE-0493 在 Swift 6.4 支持异步上下文内的 `defer { await … }`。离开作用域时隐式等待异步清理，多个 defer 仍逆序运行；它不自动屏蔽任务取消。[^s8]

以下依据提案的 Proposed solution 改写，以函数参数表示工作与清理操作：[^s8]

```swift
func performJob(work: () async throws -> Void,
                cleanup: () async -> Void) async throws {
    // 正常返回或抛错离开作用域前，等待清理完成。
    defer { await cleanup() }
    try await work()
}
```



**相关更新：任务取消屏蔽（SE-0504）。** `withTaskCancellationShield` 在当前任务中临时屏蔽取消观察：块内 `Task.isCancelled` 返回 false，`Task.checkCancellation()` 不因当前任务已取消而抛错；退出后仍能看到取消状态。它也阻止外层取消自动传给块内创建的结构化子任务，但显式取消子任务仍有效。只在一个已存在的任务组上包住 `group.addTask` 调用，不足以屏蔽子任务自身的执行；应覆盖任务组生命周期或在子任务内部使用屏蔽块。提案同时提供同步和异步形式，因此无需仅为避开取消而新建非结构化 Task。[^s37]

### 4.4 用于名称消歧的模块选择器（SE-0491）

**事实。** SE-0491 标注 Swift 6.3 已实现。`Module::name` 将候选限定为指定模块声明或重导出的名字，解决模块名与类型名等冲突；它不能绕过导入要求或访问控制。[SE-0491 原文](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0491-module-selectors.md#effects-on-lookup)



### 5.2 Borrow 和 Mutate 访问器

**原提案。** [SE-0507 — Borrow and Mutate Accessors](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0507-borrow-accessors.md)，Swift 6.4。Motivation 指出：`get` 需复制已有值或构造新值，因此不适合复制成本高、或必须继续保留在容器中的不可复制字段。

**设计与示例。** 同一 Wrapper 持有 NC: ~Copyable 字段。旧 get { return _element } 试图复制仍留在容器中的字段，直接报错；新 borrow { return _element }／mutate { return &_element } 分别借出读取与修改访问。demo 在读取结束后再修改 Int 字段 value，演示两次访问不重叠。读借用期间不能修改本例整个 Wrapper；写借用期间其他路径不能读写整个 Wrapper。完整代码及解释见 S02。[^s10]

**收益与边界。** 可用属性或下标接口借出不可复制字段，调用方无需降级到裸指针。返回的存储须持续有效，不得借出访问器内部临时值；修改访问期间其他路径不能读写整个提供者。`mutate` 必须配合 `borrow`，当前不支持 class／actor 属性。更换已发布库的访问器可能改变生命周期限制及源码／ABI 兼容性。[^s11]



### 5.3 Iterable：迭代协议的成本模型

**事实。** SE-0516 现标注 Implemented (Swift 6.4)。其设计按批返回 Span，让 `for-in` 借用元素，支持不可复制元素以及可抛错迭代。若同时具有 Sequence 能力，现有循环优先保留 Sequence 路径，以避免改变既有语义；标准库已有 Sequence 类型的 Iterable 适配范围需按具体类型核对。[^s12][^s38]



### 5.4 Ref / MutableRef：让临时访问可以被命名

**事实。** SE-0519 标注 Swift 6.4 已实现。`Ref` 表示共享读取，`MutableRef` 表示独占修改，二者为受生命周期约束的非逃逸类型；前者可复制，后者不可复制。[^s13]



### 5.5 独占容器及其他安全库能力

UniqueBox、UniqueArray 的早期接受决定分别见 [^s14][^s15]；Swift 6.4 正式公告已介绍两种类型，SE-0527 现标注 Implemented (Swift 6.4)。两者体现以独占所有权支撑容器表达的方向，具体模块与 API 仍应以固定工具链核验。[^s38]

WWDC 同时介绍不可复制能力向常见协议扩展，以及 Continuation 等库能力；具体 API 可用性以固定工具链版本为准。[^s1]

## 6. 编译器：区分编译速度、运行速度与可预测性

### 6.1 显式内联与特化

**事实。** SE-0496 将 `@inline(always)` 标为 Swift 6.3 已实现；SE-0460 将显式特化同样标为 6.3，并使用 `@specialized`。专场的内联版本说法与发布博客的特化拼写有差异，详见第 11 节。[^s16][^s17]





### 6.2 类型检查器：减少无效搜索

**事实。** Swift 编译器维护者 2026-06-02 的说明将 6.4 工作概括为 disjunction pruning、更精确的绑定域推导及增量重算。确定不可能成功的重载候选可以提前排除；性能用例使用操作计数监测回归。该材料是大会前官方项目技术补充，不是 WWDC 专场独立发布。[^s19]



### 6.3 依赖扫描与调试信息复用

**事实。** Xcode 27 发布说明记录 Swift 依赖扫描减少重复设置和头文件搜索，同时要求单次扫描可达的 Clang 模块名唯一；LLDB 可复用显式构建的 Swift 模块/PCH，并新增 Swift task tree 命令。[^s20]



## 7. 工具链与互操作：让渐进采用可执行

### 7.1 Swift Build 的统一方向

Swift 6.3 发布材料将 SwiftPM 对 Swift Build 的集成标为预览。维护者随后在 main 切换默认后端；Swift 6.4 正式版已确认 Swift Build 成为 SwiftPM 默认构建后端，`--build-system native` 仍提供回退路径。Swift 官方 3 月文章提出减少重复构建技术、获得一致跨平台体验的目标，并介绍用大量开源包进行兼容性验证。[^s9][^s21][^s22][^s38]



### 7.2 C 兼容函数与枚举（SE-0495）

**事实。** SE-0495 标注 Swift 6.3 已实现。`@c` 将长期使用的实验属性 `@_cdecl` 正式化并扩展：全局函数采用 C 调用约定，签名只能使用 C 可表示的类型；枚举必须使用 C 兼容整数作为原始值类型。`@c` 函数和枚举可写入生成的兼容头文件。`@c @implementation` 则实现已导入 C 头文件中的函数声明，编译器检查名称与类型匹配，且不在生成头中重复输出该声明。[SE-0495 原文](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0495-cdecl.md)

**开发者收益与边界。** 旧机制中 `@_cdecl` 已能导出函数并检查签名，使用 Objective-C 可表示规则；新提案将 `@c` 限定为纯 C 可表示类型，并增加兼容头文件的 C 声明区、C 枚举与既有声明匹配，支持逐函数迁移 C 实现。按提案，在同一二进制内保持既有 C 声明而将实现迁到 Swift 可保持 ABI；这不同于给既有 Swift 函数增删 `@c`／`@objc`，或把 `@_cdecl` 改成 `@c`／`@objc`，后两类会改变 ABI。`@c` 与 `@objc` 之间切换本身保持 ABI。[ABI compatibility](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0495-cdecl.md#abi-compatibility)

**编译器实现。** Swift 6.3 按内建标量映射、类型形状递归检查与 Clang 导入身份判断 C 可表示性，不是开发者可遵循的公开协议；不会仅因自定义 Swift 结构体的字段全可表示就接受它。旧属性生成 Swift 与 C 入口，`@c` 本体只有 C 入口，但作为 Swift 函数值使用时仍可能需要适配代码。[类型规则](https://github.com/swiftlang/swift/blob/swift-6.3-RELEASE/lib/AST/ASTContext.cpp#L6354-L6389)、[递归与导入身份](https://github.com/swiftlang/swift/blob/swift-6.3-RELEASE/lib/AST/Type.cpp#L3213-L3290)、[入口区别](https://github.com/swiftlang/swift/blob/swift-6.3-RELEASE/lib/AST/Decl.cpp#L2260-L2272)。



**事实。** Swift 官方安全互操作文档通过长度、非逃逸和生命周期标注，把适用的指针/长度或 `std::span` 接口映射到 Swift 安全视图；新增安全重载不要求删除原始接口。它的安全边界不等于验证整个 C/C++ 实现。[^s23]

Xcode 27 的说明对成熟度给出具体区分：带 `__noescape` 的适用输入参数映射不再需要 SafeInteropWrappers 实验开关，而依赖 `__lifetimebound` 的返回值映射仍受开关控制。[^s20]



### 7.4 跨平台、Embedded 与生态工具

Swift 6.3 已发布官方 Android SDK；Swift-Java 是独立演进的包，其版本需与语言版本分别记录。维护者 0.3.0 说明涉及接口提取、类型处理与新构建后端兼容性。[^s9][^s24]

WWDC 展示 Embedded Swift 扩展可用语言子集及调试信息的进展，并介绍 Wasm、编辑器与工具链管理。主讲只用作覆盖边界，具体平台支持不能从“Swift 6.4”一个版本号推导。[^s1]

WWDC 还介绍了 Embedded Swift 中存在类型和非类型化 `throws` 的支持、写入 DWARF 的类型布局信息、JavascriptKit 的安全桥接，以及编辑器中的 Swiftly 与 OpenVSX 集成。[^s1]



## 8. Xcode：开发与验证工具

### 8.1 Agent 工作流的今年增量

**事实。** Xcode 26.3 已引入 coding agents。Xcode 27 进一步整合探索、计划、构建、精修和多任务组织，呈现计划、差异和预览等产物，连接项目上下文与官方文档检索。[^s25]

**设计意图。** 苹果在专场中强调开发者负责方向与架构，Agent 处理更多执行工作。其价值取决于能否调用构建、测试、预览等可观测工具，并将结果回到上下文里。模型知道最新 API、修改能编译、测试覆盖正确、需求得到满足是四个不同条件。



Xcode 27 发布说明还列出 ACP、包含 skills/MCP/agent 配置的插件、Apple specialists 及可选的文件访问安全层。[^s20]



Xcode 27 介绍未命名项目和独立 Swift 文件的预览/Playground 工作流；工具栏、主题与编辑诊断展示也有变化。[^s26]

Agent 本地化将项目上下文、String Catalog 和语言指导连接起来，仍需要审阅翻译与布局。[^s27]



## 9. 设备、测试与性能诊断

### 9.1 Device Hub：可复现的状态比截图更重要

**事实。** Device Hub 统一组织与控制设备、模拟器，提供配置、问题复现及 `devicectl` 相关工作流。[^s28]



### 9.2 Swift Testing 与 XCTest 的互操作

**原提案。** [ST-0021 — Targeted Interoperability between Swift Testing and XCTest](https://github.com/swiftlang/swift-evolution/blob/main/proposals/testing/0021-targeted-interoperability-swift-testing-and-xctest.md)，Swift 6.4。Motivation 的 assertUnique 示例在 XCTest 中能报告重复元素，替换成 Swift Testing 用例后复用同一断言却可能静默通过。Complete 模式将失败记录为当前测试的错误，并给出迁移警告；详见 S14 的同一测试前后结果对照。

**设计范围。** XCTest 的相关断言可在 Swift Testing 中报告结果；Swift Testing API 在 XCTest 已有对应能力时获得支持。Limited 仅把 Swift Testing 中的 XCTest 断言失败降为警告；所有非 None 模式下，XCTest 中的 Swift Testing 期望失败仍报错误。Strict 对相关 XCTest API 使用触发 fatalError；None 关闭互操作。XCTSkip、XCTestExpectation、XCTWaiter 不因此获得通用兼容。提案针对 Corelibs XCTest，Xcode 自带实现的 test plan 默认值另据 Apple 迁移专场说明。[^s29]



### 9.3 Instruments：把慢区分为计算、争用和阻塞

**事实。** WWDC26 的 Instruments 专场演示 Top Functions、运行比较和 Swift Executors 视图，将 Main Actor、并发 executor 及系统等待联系到响应性分析。[^s30]



### 9.4 Organizer 与 Xcode Cloud

Xcode 27 的 Organizer 更新覆盖高影响问题汇总、存储与动画卡顿指标、Metric Goals 及 Agent 辅助分析。它将发布后的观测连接回工程。[^s26]

Xcode Cloud 专场重点是接入、构建/测试、分发、webhook 与额外仓库管理的连贯体验。CI/CD、TestFlight 或 webhook 本身不能全部标为今年首次出现。[^s31]



## 12. 扩展资料

### 12.1 SwiftUI 的编译相关变化

WWDC26 的 SwiftUI 专场介绍 ContentBuilder 汇合多个 builder 的方向，并说明使用 Xcode 27 构建时可改善类型检查，不要求将部署目标全部提升到新系统。[^s32]

系统发布说明还介绍 `@State` 替换成宏实现，减少视图结构重复创建时的初始化表达式求值，同时列出源码兼容例外。不能将其描述为“宏必然比属性包装器快”，也不能把框架实现变化归因于编译器所有场景的提升。[^s33]



### 12.2 Foundation 与子进程

Swift 指南把性能收益延伸到 Foundation；ProgressManager 官方 API 提供任务进度表达及子任务进度合成。[^s6][^s34]

Subprocess 1.0 的官方提案材料反映了对执行结果、输出消费和跨平台终止语义的调整；材料处于评审状态，未作为最终稳定 tag 的依据。[^s35]

### 12.3 文档和包工具是开发体验的一部分

Swift 6.3 资料介绍 DocC 的实验性 Markdown 输出等能力。[^s9] 2026 年 8 月 Swift 官方项目进一步介绍按发布分支及 main 构建的新文档站；这是大会后补充，不纳入 WWDC 新功能计数。[^s36]



| 项目 | 记录方式 | 不作的推断 |
|---|---|---|
| Apple Clang 的 C++ operator API Notes 支持 | Xcode 27 release notes 的小范围增强 [^s20] | 不声称 Clang 全面升级到某个上游 LLVM 版本 |
| C++ 默认实参、std::function 和引用类型桥接 | 作为互操作附录阅读入口 [^s20] | 不声称所有 C++ 类型都能无损映射 |
| swift test 重复执行与结果汇总 | 作为定位不稳定用例的工具 [^s20] | 不把“重试直到通过”当作缺陷已修复 |
| 官方局部性能倍数 | 保存原始测量对象；主讲以机制为主 | 不外推到整应用，不与未测试的仓颉比较 |

## 13. 官方来源

WWDC 专场属于 2026 年大会资料。未明确日期的滚动文档不标注发布日期；Swift Evolution 链接指向主分支，状态可能继续变化。

[^s1]: Apple. [What’s new in Swift — WWDC26, Session 262](https://developer.apple.com/videos/play/wwdc2026/262/). 2026；重点章节：0:44 日常改进，12:35 C 互操作，18:08 Embedded，19:59 性能，24:29 所有权，31:11 后续发展。
[^s2]: Apple. [SDKs and system requirements — Xcode](https://developer.apple.com/xcode/system-requirements). 滚动更新；用于当前 Xcode/Swift/宿主与目标版本区分。
[^s3]: Swift Project. [SE-0390: Noncopyable structs and enums](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0390-noncopyable-structs-and-enums.md). 历史背景：所有权与参数约定。
[^s4]: Swift Project. [SE-0296: Async/await](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0296-async-await.md). 历史背景：异步类型与挂起点。
[^s5]: Swift Project. [SE-0244: Opaque Result Types](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0244-opaque-result-types.md). 历史背景：不透明类型。
[^s6]: Apple. [WWDC26 Swift guide](https://developer.apple.com/wwdc26/guides/swift/). 2026；6.4 概览与性能宣称边界。
[^s7]: Swift Project. [SE-0522: Source-Level Control Over Compiler Warnings](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0522-source-warning-control.md). 读取状态：Implemented (Swift 6.4)。
[^s8]: Swift Project. [SE-0493: Support async calls in defer bodies](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0493-defer-async.md). 读取状态：Implemented (Swift 6.4)。
[^s9]: Holly Borla, Joe Heck / Swift Project. [Swift 6.3 Released](https://www.swift.org/blog/swift-6.3-released/). 2026-03-24；版本基线，正文个别拼写与专场存在差异。
[^s10]: Swift Project. [SE-0507: Borrow and Mutate Accessors](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0507-borrow-accessors.md). 读取状态：Implemented (Swift 6.4)。
[^s11]: Swift Project. [SE-0507: Detailed design and Implications on adoption](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0507-borrow-accessors.md#implications-on-adoption). 存储有效期、独占访问与采用兼容性。
[^s12]: Swift Project. [SE-0516: Iterable](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0516-borrowing-sequence.md). 2026-09-21 复核状态：Implemented (Swift 6.4)；初版读取到的 Active review 已过时。
[^s13]: Swift Project. [SE-0519: Ref and MutableRef types for safe, first-class references](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0519-ref-mutableref-types.md). 读取状态：Implemented (Swift 6.4)。
[^s14]: Swift Language Steering Group / Ben Cohen. [Accepted — SE-0517: UniqueBox](https://forums.swift.org/t/accepted-se-0517-uniquebox/86138). 2026-04-21；接受决定。
[^s15]: Swift Language Steering Group / Steve Canon. [Accepted in Principle — SE-0527: UniqueArray](https://forums.swift.org/t/accepted-in-principle-se-0527-uniquearray/86943). 2026-05-27 的历史决定；[当前提案](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0527-rigidarray-uniquearray.md) 已标 Implemented (Swift 6.4)。
[^s16]: Swift Project. [SE-0496: @inline(always) attribute](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0496-inline-always.md). 读取状态：Implemented (Swift 6.3)。
[^s17]: Swift Project. [SE-0460: Explicit Specialization](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0460-specialized.md). 读取状态：Implemented (Swift 6.3)。
[^s18]: Swift Project. [SE-0193: Cross-module inlining and specialization](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0193-cross-module-inlining-and-specialization.md). 历史背景：实现可见性与跨模块优化。
[^s19]: Slava Pestov / Swift Compiler. [Recent improvements to the type checker](https://forums.swift.org/t/recent-improvements-to-the-type-checker/87048). 2026-06-02；大会前技术补充。
[^s20]: Apple. [Xcode 27 Beta Release Notes](https://developer.apple.com/documentation/xcode-release-notes/xcode-27-release-notes?changes=latest_minor). 读取到的 Beta 条目；用于具体工具变化与限制，不代替 RC 系统要求。
[^s21]: Owen Voorhees / SwiftPM. [SwiftPM development update: default build system change](https://forums.swift.org/t/swiftpm-development-update-default-build-system-change/85548). 2026-03-24；main 切换默认后端。
[^s22]: Owen Voorhees, Dave Lester / Swift Project. [What’s new in Swift: March 2026 Edition](https://www.swift.org/blog/whats-new-in-swift-march-2026/). 2026-03-31；构建统一的目标与兼容性方法。
[^s23]: Swift Project. [Safely Mixing Swift and C/C++](https://www.swift.org/documentation/cxx-interop/safe-interop/). 滚动文档；部分说明仍基于 Swift 6.2，开关状态结合 s20 阅读。
[^s24]: Konrad Malawski / Swift-Java. [Swift-java 0.3.0 released!](https://forums.swift.org/t/swift-java-0-3-0-released/86716). 2026-05-14；独立包版本与兼容性。
[^s25]: Apple. [Xcode, agents, and you — WWDC26, Session 259](https://developer.apple.com/videos/play/wwdc2026/259/). 2026；2:06 Explore，7:38 Build，13:44 Refine，18:25 Orchestrate。
[^s26]: Apple. [What’s new in Xcode 27 — WWDC26, Session 258](https://developer.apple.com/videos/play/wwdc2026/258/). 2026；工作区、轻量原型与 Organizer。
[^s27]: Apple. [WWDC26 Xcode guide](https://developer.apple.com/wwdc26/guides/xcode/). 2026；本地化与工具概览。
[^s28]: Apple. [Get the most out of Device Hub — WWDC26, Session 260](https://developer.apple.com/videos/play/wwdc2026/260/). 2026；1:04 概览，8:08 问题复现，15:52 devicectl。
[^s29]: Apple. [Migrate to Swift Testing — WWDC26, Session 267](https://developer.apple.com/videos/play/wwdc2026/267/). 2026；跨框架断言的分级策略。
[^s30]: Apple. [Profile, fix, and verify: Improve app responsiveness with Instruments — WWDC26, Session 268](https://developer.apple.com/videos/play/wwdc2026/268/). 2026；7:06 采样可视化，16:01 执行争用，20:29 系统阻塞。
[^s31]: Apple. [Build, deliver, and automate with Xcode Cloud — WWDC26, Session 261](https://developer.apple.com/videos/play/wwdc2026/261/). 2026；2:07 接入，6:42 分发，9:21 Webhooks，11:22 额外仓库。
[^s32]: Apple. [What’s new in SwiftUI — WWDC26, Session 269](https://developer.apple.com/videos/play/wwdc2026/269/). 2026；ContentBuilder 与构建性能相关说明。
[^s33]: Apple. [iOS & iPadOS 27 Beta Release Notes](https://developer.apple.com/documentation/ios-ipados-release-notes/ios-ipados-27-release-notes). 读取到的 Beta 文档；State 宏实现及兼容性。
[^s34]: Apple. [ProgressManager — Foundation](https://developer.apple.com/documentation/foundation/progressmanager). 读取时标为 Beta；进度 API。
[^s35]: Charles Hu / Swift Foundation. [Pitch: Subprocess 1.0](https://forums.swift.org/t/pitch-subprocess-1-0/85589). 2026-03-25；API 演进提案，不当作最终发布凭据。
[^s36]: Joseph Heck / Swift Project. [Swift’s New Documentation Site](https://forums.swift.org/t/swifts-new-documentation-site/89192). 2026-08-26；大会后的官方项目补充。
[^s37]: Swift Project. [SE-0504: Task Cancellation Shields](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0504-task-cancellation-shields.md). 用于取消屏蔽与子任务取消的语义边界。
[^s38]: Joe Heck, Holly Borla / Swift Project. [Swift 6.4 Released](https://www.swift.org/blog/swift-6.4-released/). 2026-09-15；正式版本、Swift Build 默认、标准库与目标支持。
[^s39]: Apple. [Developer Releases](https://developer.apple.com/news/releases/). 2026-09-14 的 Xcode 27 (27A266a) 正式发布记录；与 2026-09-09 RC 分开。
