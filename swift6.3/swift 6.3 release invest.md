# Swift 6.3 Release 详细介绍

> 基于 [Swift.org 官方发布博文](https://www.swift.org/blog/swift-6.3-released/) (2026-03-24) 整理。

---

## 概览

Swift 6.3 进一步将 Swift 推向全栈各层——从嵌入式固件、互联网级服务到全功能移动应用。本版本核心亮点：

- **更灵活的 C 互操作性**
- **跨平台构建工具改进**
- **嵌入式 Swift 增强**
- **首个官方 Swift SDK for Android**

---

## 1. 语言与标准库

### 1.1 `@c` 属性 — 暴露 Swift 函数/枚举给 C

`@c` 让 Swift 函数和枚举能被同项目中的 C 代码调用。编译器自动在生成的 C 头文件中加入对应声明。

```swift
// Swift 侧
@c
func callFromC() { print("Hello from Swift!") }
```

```c
// 生成的 C 头文件
void callFromC(void);
```

**自定义 C 名称：**

```swift
@c(MyLibrary_callFromC)
func callFromC() { }
```

```c
// 生成: void MyLibrary_callFromC(void);
```

**搭配 `@implementation` — 用 Swift 实现 C 头文件中声明的函数：**

```c
// C 头文件
void callFromC(void);
```

```swift
// Swift 实现
@c @implementation
func callFromC() { print("Swift implementation") }
```

此时 Swift 会校验 Swift 函数签名与 C 头文件声明一致，而不会再次生成声明。

### 1.2 性能控制属性

三个新属性让库作者对客户端编译器优化有更精细控制：

- **`@specialize`** — 为泛型 API 的常用具体类型提供预特化实现
- **`@inline(always)`** — 保证对函数直接调用的内联展开（谨慎使用，会增大代码体积）
- **`@export(implementation)`** — 在 ABI 稳定库中向客户端暴露函数实现，允许更多编译器优化

```swift
@specialize(where T == Int)
func process<T>(_ value: T) { }

@inline(always)
func criticalPath() -> Int { return 42 }

@export(implementation)
public func libraryUtility() { }
```

### 1.3 模块名选择器 (Module Selectors)

用 `::` 语法消除多模块同名 API 歧义：

```swift
import ModuleA
import ModuleB

let x = ModuleA::getValue() // ModuleA 的版本
let y = ModuleB::getValue() // ModuleB 的版本
```

也可用 `Swift` 模块名访问标准库中的并发和字符串处理 API：

```swift
let task = Swift::Task {
    // async work
}
```

---

## 2. 包管理与构建改进

### 2.1 Swift Build 预览版集成

Swift 6.3 将 [Swift Build](https://github.com/swiftlang/swift-build) 预览版集成到 Swift Package Manager 中，提供跨所有支持平台的统一构建引擎。

```bash
# 尝试 Swift Build 预览
swift build --build-system swiftbuild
```

### 2.2 SwiftPM 其他改进

| 改进项 | 说明 |
|--------|------|
| **预构建 Swift Syntax** | 宏专用库可共享 swift-syntax 预编译二进制 |
| **灵活的继承文档** | 控制符号图生成插件是否包含继承文档 |
| **可发现的包特性** | `swift package show-traits` 查看包支持的特性 |

```bash
swift package show-traits
# 列出当前包所有可配置 trait
```

---

## 3. 核心库更新

### 3.1 DocC 文档编译器

三项新的实验性能力：

**Markdown 输出：**
```bash
docc convert --enable-experimental-markdown-output
```

**静态 HTML SEO 增强：** 每个页面在 `<noscript>` 中嵌入摘要（标题、描述、可用性、声明、讨论），提升搜索引擎可发现性和无障碍访问。

**代码块注解：**

````swift
// nocopy — 禁用复制按钮
```swift, nocopy
let config = loadDefaultConfig()
```

// highlight — 高亮指定行
```swift, highlight=[1, 3]
let name = "World"       // 高亮
let greeting = "Hello"
print("\(greeting), \(name)!")  // 高亮
```

// showLineNumbers + wrap
```swift, showLineNumbers, wrap=80
func example() { /* ... */ }
```
````

### 3.2 Swift Testing

| 新特性 | 说明 |
|--------|------|
| **警告 Issue** | `Issue.record("msg", severity: .warning)` — 记录警告但不标记测试失败 |
| **测试取消** | `try Test.cancel()` — 取消当前测试及其任务层级 |
| **图片附件** | Apple/Windows 平台支持在测试中附加常见图片格式 |

```swift
@Test func example() {
    // 记录警告而非失败
    Issue.record("Something suspicious happened", severity: .warning)

    // 条件取消
    if someCondition {
        try Test.cancel()
    }
}
```

---

## 4. 平台与环境

### 4.1 Embedded Swift

嵌入式 Swift 在 6.3 中获得广泛改进：
- 增强的 C 互操作性
- 更好的调试支持
- 向完整链接模型迈出重要步伐

详见：[Embedded Swift Improvements coming in Swift 6.3](https://www.swift.org/blog/embedded-swift-improvements-coming-in-swift-6.3/)

### 4.2 Swift SDK for Android 🎉

Swift 6.3 包含**首个官方 Android SDK**：

- 用 Swift 开发原生 Android 程序
- 更新 Swift Package 以支持 Android 构建目标
- 通过 [Swift Java](https://github.com/swiftlang/swift-java) + [Swift Java JNI Core](https://github.com/swiftlang/swift-java-jni-core) 将 Swift 代码集成到现有 Kotlin/Java Android 应用中

```bash
# 安装 Android SDK
swift sdk install https://github.com/swiftlang/swift-sdk-android

# 构建 Android 目标
swift build --swift-sdk aarch64-unknown-linux-android
```

---

## 5. 快速开始

```bash
# 安装 Swift 6.3
# 详见 https://www.swift.org/install/

# 验证版本
swift --version
# Swift version 6.3
```

---

## 参考资料

- [Swift 6.3 官方发布博文](https://www.swift.org/blog/swift-6.3-released/)
- [Swift Evolution Dashboard (version=6.3)](https://www.swift.org/swift-evolution/#?version=6.3)
- [SwiftPM 6.3 Release Notes](https://docs.swift.org/swiftpm/documentation/packagemanagerdocs/6.3)
- [Swift SDK for Android 入门](https://www.swift.org/documentation/articles/swift-sdk-for-android-getting-started.html)
- [Embedded Swift 改进](https://www.swift.org/blog/embedded-swift-improvements-coming-in-swift-6.3/)
- [Swift Build 预览](https://docs.swift.org/swiftpm/documentation/packagemanagerdocs/swiftbuildpreview)