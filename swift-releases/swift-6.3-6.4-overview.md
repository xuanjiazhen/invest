# Swift 6.3 → 6.4 新特性详解

> 基于 [Swift.org 官方发布博文](https://www.swift.org/blog/swift-6.3-released/) (2026-03-24) 与 [WWDC 2026: What's new in Swift](https://developer.apple.com/videos/play/wwdc2026/262/) 整理。

---

## 时间线

| 版本 | 发布日期 | 主要来源 |
|------|----------|----------|
| Swift 6.3 | 2026-03-24 | [swift.org 发布博文](https://www.swift.org/blog/swift-6.3-released/) |
| Swift 6.4 | 2026-06 (WWDC26) | [WWDC 2026 Session 262](https://developer.apple.com/videos/play/wwdc2026/262/) |

---

## 第一部分：Swift 6.3 新特性

### 1. `@c` 属性 — Swift → C 双向互操作

> 提案: [SE-0495](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0495-cdecl.md) · 动机：Linux 移植与系统框架向 Swift 迁移需要双向 C 互操作。此前 `@_cdecl` 仅为内部属性，6.3 将其正式化。

`@c` 让 Swift 函数和枚举能被同项目中的 C 代码调用。编译器自动在生成的 C 头文件中加入对应声明。

```swift
// 基础用法
@c
func callFromC() { print("Hello from Swift!") }
// → 生成 C 头: void callFromC(void);

// 自定义 C 名称
@c(MyLibrary_callFromC)
func callFromC() { }
// → 生成: void MyLibrary_callFromC(void);

// 用 Swift 实现 C 头中声明的函数（Swift 校验签名一致性）
@c @implementation
func callFromC() { print("Swift implementation") }
```

### 2. 性能控制属性

> 提案: [SE-0460](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0460-specialized.md) · [SE-0496](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0496-inline-always.md) · [SE-0497](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0497-definition-visibility.md) · 动机：此前 `@_specialize`、`@_inline` 等为下划线属性，库作者无法在稳定的公共 API 中使用。6.3 将其正式化并提供 ABI 稳定性保证。

| 属性 | 作用 |
|------|------|
| `@specialize(where T == Int)` | 为泛型 API 的常用具体类型提供预特化实现 |
| `@inline(always)` | 保证函数直接调用内联展开（谨慎使用，增大代码体积） |
| `@export(implementation)` | 在 ABI 稳定库中暴露实现体，允许跨模块优化 |

```swift
@specialize(where T == Int)
func process<T>(_ value: T) { }

@inline(always)
func criticalPath() -> Int { return 42 }

@export(implementation)
public func libraryUtility() { }
```

### 3. 模块名选择器 `::`

> 提案: [SE-0491](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0491-module-selectors.md) · 动机：大型项目中多模块依赖常出现同名 API 冲突，此前只能通过全限定名或重构规避，模块选择器提供了显式消歧语法。

```swift
import ModuleA
import ModuleB

let x = ModuleA::getValue()  // ModuleA 的版本
let y = ModuleB::getValue()  // ModuleB 的版本

// 也可用 Swift 模块名访问标准库
let task = Swift::Task { /* async work */ }
```

### 4. Swift Build 预览版 + SwiftPM 改进

- **Swift Build** 预览版集成到 SwiftPM，统一跨平台构建引擎
- 预构建 Swift Syntax 支持宏专用库
- `swift package show-traits` 查看包特性
- 灵活的继承文档控制

### 5. DocC 增强

- Markdown 输出 (`--enable-experimental-markdown-output`)
- 代码块注解：`nocopy` / `highlight=[1,3]` / `showLineNumbers` / `wrap=80`
- 静态 HTML SEO 增强（`<noscript>` 嵌入摘要）

### 6. Swift Testing

| 新特性 | 说明 |
|--------|------|
| 警告 Issue | `Issue.record("msg", severity: .warning)` |
| 测试取消 | `try Test.cancel()` |
| 图片附件 | Apple/Windows 平台 |

### 7. 平台

- **Embedded Swift**：增强 C 互操作、更好调试支持、完整链接模型
- **Android SDK**：首个官方 Swift SDK for Android

---

## 第二部分：Swift 6.4 新特性（WWDC 2026）

### 1. 日常语言改进

**可选括号省略：**
```swift
// 6.4: 条件语句中的括号可省略
if someCondition {
    doWork()
}
```

**`weak let`：**
> 提案: [SE-0481](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0481-weak-let.md)

```swift
class Observer {
    weak let subject: SomeClass?  // 不可变的弱引用
}
```

**`~Sendable` 抑制并发警告：**
> 提案: [SE-0518](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0518-tilde-sendable.md) · 动机：某些类型（如与 C 互操作的指针类型）客观上不满足 Sendable，但开发者确知使用安全。提供显式标记避免编译器持续产生噪声警告。

```swift
// 标记类型有意不满足 Sendable，抑制编译器诊断
struct MyType: ~Sendable { }
```

**新成员初始化器：**
```swift
struct Meeting {
    var topic: String
    var scheduledAt: Date
    var attendees: [String] = []  // 有默认值

    // 6.4: 自动生成 memberwise init，仅要求无默认值的参数
    // internal init(topic: String, scheduledAt: Date)
}
```

### 2. `anyAppleOS` 可用性

告别冗长的多平台声明：

```swift
// 之前 (6.3)
@available(macOS 27, iOS 27, watchOS 27, tvOS 27, visionOS 27, *)
func showStatus() { }

#if os(macOS) || os(iOS) || os(watchOS) || os(tvOS) || os(visionOS)
func makeLiveActivityWidget() -> some Widget { }
#endif

// 6.4: 一行搞定
@available(anyAppleOS 27, *)
func showStatus() { }

#if os(anyAppleOS)
func makeLiveActivityWidget() -> some Widget { }
#endif
```

### 3. `@diagnose` 属性

> 提案: [SE-0522](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0522-source-warning-control.md) · 动机：团队希望将特定警告升级为错误（或降级为备注），但此前仅能通过命令行全局控制。`@diagnose` 提供声明级细粒度控制。

控制单个声明的警告行为：

```swift
@diagnose(warning: .unusedVariable, severity: .error)
func criticalFunction() {
    let x = 1  // warning → error
}
```

### 4. Subprocess 1.0 库

全新的子进程管理库：

```swift
import Subprocess

let process = try Subprocess(
    executable: .named("git"),
    arguments: ["status", "--short"]
)
let output = try await process.launch()
print(output.standardOutput)
```

### 5. Foundation 更新

跨平台 Foundation 改进，增强非 Apple 平台上的兼容性和功能覆盖。

### 6. 跨平台扩展

**Swift-Java 增强：**
```swift
// Java 可调用 Swift async/throwing 函数
// Java 类可遵循 Swift 协议
// 约束扩展支持
```

**WebAssembly & JavaScriptKit（40x 性能提升）：**
```swift
// JS → Swift 安全桥接性能提升 40 倍
import JavaScriptKit

let document = JSObject.global.document
let element = document.getElementById("app")
```

**VSCode 扩展改进：**
- Swiftly 集成，统一工具链管理
- 上架 OpenVSX 市场（Cursor / VSCodium 可用）

### 7. Embedded Swift 增强

- 支持 existential 类型
- 支持 untyped throws
- 改进 DWARF 调试信息生成

### 8. 所有权系统与非可复制类型

> 提案: [SE-0390](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0390-noncopyable-structs-and-enums.md) · [SE-0427](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0427-noncopyable-generics.md) · [SE-0515](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0515-noncopyable-reduce.md) · [SE-0528](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0528-noncopyable-continuation.md) · 动机：资源管理（文件句柄、内存缓冲区）需要所有权唯一性保证，避免 double-free 和 use-after-free。非可复制类型在编译期强制执行所有权规则。

```swift
// 非可复制类型：所有权唯一，避免意外复制
struct Buffer: ~Copyable {
    let ptr: UnsafeMutablePointer<Int>

    consuming func dispose() {
        ptr.deallocate()
    }
}
```

### 9. 标准库新类型

> 提案: [SE-0517](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0517-uniquebox.md) · [SE-0527](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0527-rigidarray-uniquearray.md) · [SE-0519](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0519-ref-mutableref-types.md) · 动机：非可复制类型需要配套的标准库容器，`UniqueBox` 提供唯一所有权堆分配，`UniqueArray` 提供动态数组，`Ref` 提供引用计数抽象。

| 类型 | 说明 |
|------|------|
| `UniqueBox<T>` | 唯一所有权的堆分配值 |
| `UniqueArray<T>` | 唯一所有权的动态数组 |
| `Ref<T>` | 引用计数包装器 |

```swift
let box = UniqueBox(42)
let arr: UniqueArray = [1, 2, 3]
let ref = Ref(wrapped: MyClass())
```

### 10. Iterable 协议与 Borrow/Mutate 访问器

> 提案: [SE-0507](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0507-borrow-accessors.md) · [SE-0516](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0516-borrowing-sequence.md) · 动机：精细控制属性访问的所有权语义——区分只读借用（borrow）和可变借用（mutate），在编译期保证无数据竞争。

```swift
// Borrow/Mutate 访问器：精细控制属性访问模式
var items: [Item] {
    _read { yield storage.items }     // borrow
    _modify { yield &storage.items }  // mutate
}
```

---

## 快速开始

```bash
# 安装最新 Swift
# https://www.swift.org/install/

# 尝鲜 Swift 6.4 快照
# https://www.swift.org/download/#snapshots

swift --version
```

---

## 提案索引

### Swift 6.3 相关提案

| 提案编号 | 标题 | 特性 |
|----------|------|------|
| [SE-0460](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0460-specialized.md) | Specialized | `@specialize` 属性 |
| [SE-0491](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0491-module-selectors.md) | Module Selectors | `::` 模块选择器 |
| [SE-0495](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0495-cdecl.md) | `@c` Attribute | `@c` / `@c(asmname)` |
| [SE-0496](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0496-inline-always.md) | Inline Always | `@inline(always)` |
| [SE-0497](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0497-definition-visibility.md) | Definition Visibility | `@export(implementation)` |

### Swift 6.4 相关提案

| 提案编号 | 标题 | 特性 |
|----------|------|------|
| [SE-0390](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0390-noncopyable-structs-and-enums.md) | Noncopyable Structs and Enums | `~Copyable` 基础 |
| [SE-0427](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0427-noncopyable-generics.md) | Noncopyable Generics | 泛型非可复制类型 |
| [SE-0481](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0481-weak-let.md) | Weak Let | `weak let` 不可变弱引用 |
| [SE-0507](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0507-borrow-accessors.md) | Borrow Accessors | `_read` / `_modify` 访问器 |
| [SE-0515](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0515-noncopyable-reduce.md) | Noncopyable Reduce | 非可复制类型的 reduce 操作 |
| [SE-0516](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0516-borrowing-sequence.md) | Borrowing Sequence | 借用迭代语义 |
| [SE-0517](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0517-uniquebox.md) | UniqueBox | `UniqueBox<T>` |
| [SE-0518](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0518-tilde-sendable.md) | `~Sendable` | 抑制 Sendable 诊断 |
| [SE-0519](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0519-ref-mutableref-types.md) | Ref / MutableRef | `Ref<T>` 引用计数包装器 |
| [SE-0522](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0522-source-warning-control.md) | Source Warning Control | `@diagnose` 属性 |
| [SE-0527](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0527-rigidarray-uniquearray.md) | RigidArray / UniqueArray | `UniqueArray<T>` |
| [SE-0528](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0528-noncopyable-continuation.md) | Noncopyable Continuation | 非可复制延续 |

### 其他参考

- [Swift 6.3 发布博文](https://www.swift.org/blog/swift-6.3-released/)
- [WWDC 2026: What's new in Swift (Session 262)](https://developer.apple.com/videos/play/wwdc2026/262/)
- [Swift Evolution Dashboard](https://www.swift.org/swift-evolution/)
- [SwiftPM 6.3 Release Notes](https://docs.swift.org/swiftpm/documentation/packagemanagerdocs/6.3)
- [Swift SDK for Android 入门](https://www.swift.org/documentation/articles/swift-sdk-for-android-getting-started.html)
- [Embedded Swift 改进详情](https://www.swift.org/blog/embedded-swift-improvements-coming-in-swift-6.3/)
- [Swift Build 预览](https://docs.swift.org/swiftpm/documentation/packagemanagerdocs/swiftbuildpreview)
- [Swift Java (GitHub)](https://github.com/swiftlang/swift-java)
- [Subprocess (GitHub)](https://github.com/swiftlang/swift-subprocess)
- [JavaScriptKit (GitHub)](https://github.com/swiftlang/JavaScriptKit)
