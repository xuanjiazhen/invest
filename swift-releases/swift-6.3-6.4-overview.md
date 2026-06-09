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
```swift
class Observer {
    weak let subject: SomeClass?  // 不可变的弱引用
}
```

**`~Sendable` 抑制并发警告：**
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

## 参考资源

- [Swift 6.3 发布博文](https://www.swift.org/blog/swift-6.3-released/)
- [WWDC 2026: What's new in Swift (Session 262)](https://developer.apple.com/videos/play/wwdc2026/262/)
- [Swift Evolution Dashboard](https://www.swift.org/swift-evolution/)
- [SwiftPM 6.3 Release Notes](https://docs.swift.org/swiftpm/documentation/packagemanagerdocs/6.3)
- [Swift SDK for Android 入门](https://www.swift.org/documentation/articles/swift-sdk-for-android-getting-started.html)
