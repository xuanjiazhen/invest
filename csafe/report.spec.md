# 仓颉调用 C 的内存安全问题分析

> 基于仓颉 1.1 文档与本机 Cangjie Compiler 1.1.0-beta.10，系统梳理仓颉代码调用 C 时的内存安全风险、语言已有约束、仍需人工维护的契约，以及可落地的增强方向。

## 一、结论摘要

仓颉调用 C 的安全边界可以概括为：**语言负责限制哪些类型和操作能够进入 FFI，并用 `unsafe` 显式标记危险行为；开发者仍需保证 C 声明、地址、长度、生命周期、所有权和线程契约正确。**

仓颉已经提供以下基础防线：

- `CType` 与 `@C struct` 限定可参与 C ABI 的类型和布局；
- `foreign func`、`CFunc`、原始指针读写、数组借用均进入 `unsafe` 上下文；
- `CPointer<T>` 支持类型参数、判空、读写与偏移；
- `@CallingConv` 可声明 `CDECL` 或 `STDCALL`；
- `inout` 将可变值按引用传给 C，并限定地址仅在调用期间有效；
- `acquireArrayRawData`/`releaseArrayRawData` 为仓颉数组提供成对的固定借用协议；
- Linux/OpenHarmony 的 GWP-Asan 可抽样检测部分数组越界写和未释放借用。

这些能力不能覆盖 C 边界的全部语义。当前主要风险集中在八类：

1. ABI 声明与真实 C 接口不一致；
2. 空指针、悬垂指针和错误类型转换；
3. 所有权、释放器和资源生命周期不明确；
4. 指针不携带长度导致越界；
5. 仓颉堆数组借用被越界、逃逸或漏释放；
6. `inout` 临时地址被 C 保存并延后使用；
7. 字符串编码、NUL 终止和分配释放协议不一致；
8. 回调、线程、错误处理和并发契约失配。

因此，更安全的仓颉 C-FFI 不应只增加一个新指针类型，而应形成“**绑定生成 + 契约元数据 + 作用域借用 + 安全包装 + 动态检测 + E2E 验证**”的组合方案。

## 二、分析范围与互操作模型

本报告只分析**仓颉代码调用 C**，包括：

- `foreign func` 与 `CFunc`；
- `CType`、`@C struct`、`VArray` 和 `@CallingConv`；
- `CPointer<T>`、`CString`；
- `acquireArrayRawData`/`releaseArrayRawData`；
- `inout` 引用传值；
- 调用 C 引入的线程、回调和错误边界。

不分析 C 通过 `Cangjie.h` 调用仓颉，也不讨论仓颉函数导出为 C API 的设计。

一次典型调用包含四层责任：

| 层次 | 主要责任 | 失配后果 |
|---|---|---|
| ABI 声明 | 符号、参数、返回值、布局、调用约定一致 | 参数误读、返回值截断、崩溃或数据损坏 |
| 地址契约 | 指针非空、对齐、可读写、指向正确对象 | 空指针、越界、类型混淆、非法访问 |
| 生命周期契约 | 借用期、所有权、释放器和释放时机一致 | 泄漏、悬垂、double-free、堆破坏 |
| 行为契约 | 长度、编码、线程、回调、错误码一致 | 数据破坏、竞态、死锁、语义错误 |

`unsafe` 会让责任边界可见，但不会自动证明以上契约成立。

## 三、风险全景

### 3.1 ABI 与类型映射错误

#### 风险来源

- C 的 `int64_t` 被声明为仓颉 `Int32`；
- C 的 `size_t`、`long` 等平台相关类型被映射为错误宽度；
- C 使用 packed、位域、联合体、柔性数组或条件编译，仓颉声明没有同步；
- 结构体字段顺序、嵌套结构、数组长度或对齐不同；
- C 侧调用约定与仓颉侧 `@CallingConv` 不一致；
- C 头文件升级后，手写 `foreign` 声明继续使用旧签名。

#### 仓颉已有约束

`CType` 限制 FFI 签名可使用的类型，`@C struct` 提供 C 兼容布局，`VArray<T,$N>` 将固定数组长度写入类型，`@CallingConv[CDECL|STDCALL]` 表达调用约定。

#### 仍存在的缺口

这些机制验证“声明是否合法”，不能验证“声明是否等于目标头文件”。`@C` 与 Rust `#[repr(C)]` 在此维度类似：都规定本语言一侧的布局规则，但不自动核对独立 C 声明。

#### 缓解措施

- 优先使用官方 HLE `cj-c2cj` 或社区 cjbind 生成绑定；
- CI 中对 `sizeof`、`alignof`、字段偏移和符号做跨语言断言；
- 固定目标平台和编译选项，避免直接映射含糊的 C 类型；
- 头文件变更触发绑定再生成和 E2E 测试。

### 3.2 空指针、悬垂指针与类型混淆

`CPointer<T>` 可以表示 null，`CPointer<T>()` 可构造空指针，`isNull()` 可显式判空。风险在于 FFI 签名不能强制调用方检查，也不携带生命周期。

典型场景：

- C 返回 NULL，仓颉直接 `read()` 或写入；
- C 已释放对象，仓颉仍保存并使用地址；
- 仓颉把 `CPointer<A>` 转为 `CPointer<B>` 后按错误布局访问；
- 指针算术产生对象范围之外的地址；
- C 返回栈上局部变量地址或短生命周期内部缓冲区。

`Option<CPointer<T>>` 更适合仓颉安全包装层，而不是直接替代原始 C ABI。包装层可在进入业务代码前集中判空、验证状态并转换为领域对象。

### 3.3 所有权、释放器与资源生命周期

原始指针没有表达以下信息：

- 返回值是 borrowed 还是 owned；
- 调用方是否必须释放；
- 应使用 `free`、库专用 destroy 函数还是不允许释放；
- C 是否接管传入对象；
- 同一资源能否被多个句柄共享；
- 释放是否要求特定线程或上下文。

由此产生内存泄漏、double-free、use-after-free 和分配器不匹配。较安全的包装方式是：

- 为拥有型句柄建立实现 `Resource` 的包装；
- 将 destroy 函数与构造函数绑定；
- `close()` 保证幂等，关闭后拒绝继续调用；
- 使用 `try/finally` 覆盖异常和提前返回；
- 不向业务层暴露可任意复制的裸拥有型指针。

### 3.4 长度、边界与整数换算

`CPointer<T>` 不携带长度。C 常用 `(pointer, length)`、NUL 终止、哨兵值或固定结构字段表达边界，如果仓颉调用端遗漏或误解长度，就会发生越界读写。

重点风险包括：

- 元素数与字节数混淆；
- 有符号长度转无符号后变为超大值；
- `Int64` 到 `Int32` 截断；
- `length * sizeof(T)` 溢出；
- C 在输出缓冲区中写入的数据超过容量；
- C 返回指针但未同时返回可验证长度。

应将 pointer、length、capacity 作为一个契约整体，在包装层先检查非负、上限和乘法溢出，再进入 `unsafe` 调用。固定长度 C 数组可使用 `VArray<T,$N>`，动态缓冲区应使用携带长度的包装类型。

### 3.5 仓颉堆数组借给 C

真实接口为：

```cangjie
let handle = acquireArrayRawData(values)
try {
    consume(handle.pointer, values.size)
} finally {
    releaseArrayRawData(handle)
}
```

`acquireArrayRawData` 返回数组原始数据的 handle，C 侧使用 `handle.pointer`；`releaseArrayRawData` 接收该 handle。两者都需要 `unsafe`。

借用期间必须满足：

- C 访问范围不超过数组长度；
- C 不调用 `free`；
- C 不保存地址供 release 后使用；
- 仓颉所有控制流都执行 release；
- C 与仓颉对元素类型、长度单位和可写性理解一致；
- 多线程访问遵守同步约束。

违规后果包括仓颉堆越界写、借用泄漏和 release 后悬垂访问。GWP-Asan 可在 Linux/OpenHarmony 抽样发现部分问题，但不能覆盖所有访问，也不能替代契约验证。

### 3.6 `inout` 暴露临时地址

`inout` 是 CFunc 调用点的引用传值表达式：

```cangjie
foreign func write_value(p: CPointer<Int32>): Unit

var value: Int32 = 0
unsafe { write_value(inout value) }
```

仓颉对可使用 `inout` 的对象做限制：对象必须可变并满足 `CType`，不能是字面量、`let`、入参或临时表达式，也不能直接或间接来自 class 实例成员。传给 C 的地址仅在该次调用期间保证有效。

主要风险不是调用期内的正常写入，而是 C 将地址保存到全局变量、异步任务或回调上下文，在调用返回后再次访问。编译器可以约束仓颉调用点，无法证明任意 C 实现没有让地址逃逸。

### 3.7 字符串边界

`CString` 表达 C 的 NUL 终止字符串视图，可判空、测长并复制成仓颉 `String`。从仓颉 `String` 创建 C 字符串可使用 `LibC.mallocCString`，使用后必须由匹配的释放函数清理。

风险包括：

- C 返回的字节不是约定编码；
- 输入包含内嵌 NUL，C 只看到前缀；
- C 返回的地址未 NUL 终止；
- 返回地址属于静态区、调用方所有或新分配内存，但仓颉误判所有权；
- C 写入只读字符串或越过目标容量；
- 仓颉用错误释放器清理 C 返回字符串。

安全包装必须同时记录编码、最大长度、可写性、所有权和释放器，而不能只把 `CString` 转为 `String`。

### 3.8 回调、线程、并发与错误边界

CFunc lambda 不能捕获变量，这减少了闭包环境跨边界的问题，但回调仍涉及函数指针和 userdata 的联合生命周期：

- C 在注销后继续调用回调；
- userdata 已释放或被错误转换；
- 回调发生在未预期线程；
- 回调与销毁并发，产生竞态；
- C 长时间阻塞占用执行仓颉线程的 native 线程；
- C TLS、线程亲和性与仓颉线程调度假设冲突；
- C 通过错误码、`errno`、部分初始化结果或 `longjmp` 离开，清理逻辑没有执行。

包装层应明确注册、注销、并发和重入协议，将错误码转换为仓颉结果，并确保 C 异常机制不越过语言边界。

## 四、风险矩阵

| 风险类别 | 主要后果 | 仓颉现有防线 | 关键剩余责任 |
|---|---|---|---|
| ABI/布局失配 | 数据误读、崩溃、内存破坏 | `CType`、`@C`、`VArray`、`@CallingConv` | 与真实头文件和目标平台一致 |
| null/悬垂/类型混淆 | 非法访问、use-after-free | `isNull()`、unsafe 指针操作 | 生命周期、有效对象与正确类型 |
| 所有权/释放器 | 泄漏、double-free、堆破坏 | 可用 `Resource`、`try/finally` 包装 | owned/borrowed 与 destroy 契约 |
| 长度/整数 | 越界读写、信息泄漏 | 固定数组 `VArray` | pointer+len+capacity 统一校验 |
| 堆数组借用 | 仓颉堆破坏、借用泄漏 | acquire/release handle、GWP-Asan | 不逃逸、不 free、不越界、必 release |
| `inout` 地址 | 调用返回后悬垂访问 | 调用点限制、调用期有效规则 | C 不保存地址 |
| 字符串 | 越界、乱码、错误释放 | `CString`、`mallocCString` | 编码、NUL、容量、所有权 |
| 回调/并发/错误 | 竞态、死锁、悬垂回调 | CFunc 限制、unsafe 边界 | 注册期、线程、重入、清理协议 |

风险等级取决于 C API 是否处理外部输入、是否跨线程或长期保存地址。不能仅凭 API 类型断言所有场景都可被利用，但所有高权限或不可信输入场景都应按高风险边界治理。

## 五、可运行 E2E 案例

以下案例覆盖 `foreign func`、`unsafe`、`inout`、数组借用、长度传递和成对释放。

C 动态库：

```c
#include <stdint.h>

__declspec(dllexport) void write_value(int32_t *p) {
    if (p) *p = 42;
}

__declspec(dllexport) int64_t sum_values(const int32_t *p, int64_t n) {
    int64_t sum = 0;
    for (int64_t i = 0; i < n; ++i) sum += p[i];
    return sum;
}
```

仓颉调用端：

```cangjie
foreign func write_value(p: CPointer<Int32>): Unit
foreign func sum_values(p: CPointer<Int32>, n: Int64): Int64

main(): Int64 {
    var value: Int32 = 0
    var values = [Int32(10), Int32(20), Int32(30)]
    unsafe {
        write_value(inout value)
        let handle = acquireArrayRawData(values)
        try {
            if (sum_values(handle.pointer, values.size) != 60) { return 3 }
        } finally {
            releaseArrayRawData(handle)
        }
    }
    if (value == 42) { 0 } else { 4 }
}
```

本机验证环境与结果：

- Cangjie Compiler `1.1.0-beta.10 (cjnative)`；
- 目标 `x86_64-w64-mingw32`；
- Clang 构建 C DLL：退出码 0；
- `cjc` 编译链接仓颉调用端：退出码 0；
- 程序运行：退出码 0。

## 六、竞品参照

竞品比较只用于寻找增强手段，不把“进入 unsafe 区域”误认为已经消除风险。

| 维度 | 仓颉 | Rust | Swift | Go/cgo |
|---|---|---|---|---|
| C 布局 | `CType` + `@C struct`；需核对头文件 | `#[repr(C)]`；需核对头文件 | Clang importer 降低手写漂移 | cgo 从 C 声明生成桥接 |
| 原始指针 | `CPointer` 无生命周期/长度/所有权 | raw pointer 同样不受 borrow checker 自动保护 | `UnsafePointer` 本身不追踪生命周期 | `unsafe.Pointer` 本身不追踪生命周期 |
| 可空性 | null + `isNull()`；包装层可用 Option | raw pointer 可 null；安全层常用 `NonNull`/Option | importer 常呈 Optional | nil 可表达，仍需主动检查 |
| 堆借用 | acquire/release handle + unsafe | raw pointer + unsafe 契约 | `withUnsafe*` 词法作用域 | cgo 指针保留规则与复制策略 |
| 栈地址 | `inout` 仅调用期有效 | 引用转 raw 后仍依赖 C 契约 | `withUnsafe*` 期间有效 | C 不应在调用后保留 Go 指针 |
| 长度 | `VArray` 或 pointer+len | raw pointer+len，安全层可构造 slice | BufferPointer 可组合地址与 count | C 指针无长度，Go slice 仅在 Go 侧有长度 |
| 绑定工具 | HLE `cj-c2cj`、社区 cjbind | bindgen 等生态 | Clang importer | cgo |

可借鉴的重点不是把 `CPointer` 换成另一种 raw pointer，而是：

- Swift 的作用域借用 API；
- Rust 生态中的所有权包装、bindgen 和 layout tests；
- Go/cgo 的指针保留规则、运行时检查和复制优先策略；
- 三者更成熟的绑定生成与持续验证工具链。

## 七、更安全的 C-FFI 机会

### P0：让声明可生成、可核验

- 扩大头文件到仓颉绑定的覆盖范围；
- 生成 `sizeof`/`alignof`/字段偏移断言；
- 在 CI 检测头文件与生成绑定漂移；
- 对调用约定、目标平台和编译选项形成显式清单。

### P0：为绑定增加契约元数据

为参数和返回值记录：

- `nullable` / `nonnull`；
- `borrowed` / `owned` / `transferred`；
- `length-of` / `capacity-of` / 长度单位；
- allocator / deallocator；
- valid-until / callback scope；
- thread / reentrant / blocking；
- error-code 与部分初始化规则。

生成器据此生成判空、长度检查、释放和错误转换代码。

### P1：提供作用域借用封装

为数组提供类似以下形态的安全封装：

```cangjie
withArrayRawData(values) { pointer, length =>
    unsafe { consume(pointer, length) }
}
```

封装内部 acquire，在 `finally` 中 release；类型和文档明确指针不得逃逸闭包。相同模式可用于 `inout`、CString 临时分配和回调注册。

### P1：将 raw 层与业务层隔离

- `foreign` 声明和裸指针仅存在于内部模块；
- 对外返回 Option、`Resource`、复制后的 `String`/`Array` 或带长度视图；
- 创建和销毁函数成对生成；
- 关闭后的资源拒绝访问；
- 同一套包装集中处理线程与错误契约。

### P2：组合动态检测

- Linux/OpenHarmony 启用仓颉 GWP-Asan；
- C/C++ 侧启用 ASan/UBSan；
- 对长度、null、异常返回、重复关闭和并发销毁做模糊测试；
- 所有绑定在真实 C 库上执行编译、链接、运行 E2E，而非只验证仓颉语法。

## 八、最终判断

仓颉调用 C 已具备 C 兼容类型、unsafe 标记、判空、调用约定、数组借用和 `inout` 调用期限制等基础设施。风险的核心不在于缺少一个“安全”关键字，而在于 **C ABI 与语义契约分散在头文件、文档和人工约定中，尚未完整进入类型、生成器和验证链路**。

安全增强的优先路线应是：先减少手写 ABI，再把可空性、长度、所有权、释放器和有效期变成可生成元数据；随后以作用域 API 和 `Resource` 包装收窄 raw pointer 暴露面；最后用跨语言 E2E 和动态检测持续验证。这样才能同时降低 ABI 漂移、越界、泄漏、悬垂和并发误用，而不是只修补单一案例。
