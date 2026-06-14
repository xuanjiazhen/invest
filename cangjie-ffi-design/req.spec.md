# 从 C 调用仓颉：`@C` 导出函数与自动生成头文件

* 提案编号: CJ-0001
* 状态: Pitch（草案）
* 关联机制: `@C`、`foreign`、`CFunc`、`CType`
* 参考蓝本: [Swift SE-0495 `@c`](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0495-cdecl.md)、[Go cgo `//export`](https://pkg.go.dev/cmd/cgo)

## 目录

* [引言](#引言)
* [动机](#动机)
* [提案概述](#提案概述)
  * [`@C` 导出函数](#c-导出函数)
  * [`@C[cName]` 自定义符号名](#ccname-自定义符号名)
  * [扩展可用类型](#扩展可用类型)
  * [编译期自动生成头文件](#编译期自动生成头文件)
  * [隐藏运行时加载过程](#隐藏运行时加载过程)
* [详细设计](#详细设计)
  * [语法](#语法)
  * [导出函数的类型检查](#导出函数的类型检查)
  * [类型映射](#类型映射)
  * [头文件生成规则](#头文件生成规则)
  * [运行时封装与初始化时序](#运行时封装与初始化时序)
  * [所有权与生命周期](#所有权与生命周期)
* [源码兼容性](#源码兼容性)
* [ABI 兼容性](#abi-兼容性)
* [对采用的影响](#对采用的影响)
* [未来方向](#未来方向)
* [备选方案](#备选方案)
* [参考资料](#参考资料)

## 引言

仓颉当前已具备完整的“仓颉调用 C”互操作能力：通过 `foreign` 声明导入 C 符号、用 `@C` 修饰可与 C 共享内存布局的结构体、用 `CFunc<(...)->...>` 表示 C 函数指针，并以 `CType` 约束限定可跨越 FFI 边界的类型。

但反方向——“**C 调用仓颉**”——目前只能依赖运行时在 `Cangjie.h` 中暴露的一组底层 C 接口（`InitCJRuntime`、`LoadCJLibraryWithInit`、`FindCJSymbol`、`RunCJTask`、`GetTaskRet` 等）。这套接口与上述语言级互操作机制彼此独立，使用门槛高。

本提案引入一种与现有 C 互操作一致的、声明式的“C 调用仓颉”能力：用 `@C` 标注顶层仓颉函数即可将其导出为具有 C 调用约定的稳定符号；编译期自动生成对应的 C 头文件；在 `CFunc` 与导出签名中放宽类型限制，允许 `String`、`Array<T> where T <: CType` 等仓颉原生类型；并把运行时初始化与协程调度封装在生成代码内部，对 C 调用方完全透明。

## 动机

考察一个最小用例：C 宿主希望调用一个仓颉函数 `add(a: Int64, b: Int64): Int64`。在现状下，C 侧需要这样写：

```c
#include "Cangjie.h"

int main(void) {
    struct RuntimeParam param = { /* 堆/GC/并发/日志 四组参数手工填写 */ };
    if (InitCJRuntime(&param) != E_OK) { /* 错误处理 */ }
    if (LoadCJLibraryWithInit("libdemo.so") != E_OK) { /* 错误处理 */ }

    // 必须知道仓颉符号被 mangle 后的真实名字
    void* fn = FindCJSymbol("libdemo.so", "_CN4demo3addEll");
    if (fn == NULL) { /* 错误处理 */ }

    // 调用必须经由协程调度，参数/返回值都以 void* 打包
    CJThreadHandle h = RunCJTask((CJTaskFunc)fn, packArgs(1, 2));
    void* ret = NULL;
    GetTaskRet(h, &ret);
    ReleaseHandle(h);

    FiniCJRuntime();
    return 0;
}
```

这暴露出四类问题：

1. **没有稳定的导出契约。** `@C` 目前只用于“仓颉调 C”，被它修饰的函数并不提供一份可被外部 C 直接 `#include` 调用的稳定 C 符号与声明。C 侧只能去猜测仓颉的名称改编（name mangling）规则。
2. **没有头文件。** C 侧没有可包含的声明，类型、参数个数、返回值全靠人工对照，极易出错且无法被编译器校验。
3. **类型受限。** 现有 FFI 仅允许 `CType`（基础数值类型、`Bool`、`Unit`、`@C struct`），无法直接传递仓颉最常用的 `String`、`Array` 等类型，用户被迫手工在 `CPointer`/`CString` 与原生类型之间来回转换。
4. **运行时细节全暴露。** 运行时初始化、库加载、符号查找、协程调度（cjthread）、句柄释放等步骤全部由 C 用户手工编排，且与“仓颉调 C”是完全无关的另一套心智模型。

对照其他语言，这些步骤本应对调用方隐藏：

* **Swift（SE-0495）** 以 `@c` 标注函数即声明其“以 C 调用约定实现于 Swift”，编译器把 C 形式的声明打印进 compatibility header，C 侧 `#include` 后即可直接调用。
* **Go（cgo）** 以 `//export` 注释导出函数，工具链生成 `_cgo_export.h`，并为 `string`/`slice` 提供 `_GoString_`、`GoSlice` 等桥接类型；Go 运行时的初始化对 C 调用方完全透明。

本提案的目标，是把“C 调用仓颉”收敛到与“仓颉调用 C”同源的一套声明式机制上，使其同样简单、可被编译器校验、且无需了解运行时内幕。

## 提案概述

### `@C` 导出函数

扩展 `@C` 的语义：当它修饰一个**顶层、非 `foreign`、非泛型**的仓颉函数时，编译器将该函数额外导出为一个使用 C 调用约定、**不参与名称改编**的稳定符号，并将其签名纳入生成的 C 头文件。

```cangjie
// demo.cj
@C
public func add(a: Int64, b: Int64): Int64 {
    return a + b
}
```

编译后，C 侧可直接：

```c
#include "demo.h"   // 编译期自动生成
int main(void) {
    int64_t r = add(1, 2);   // 运行时初始化对调用方透明
    return (int)r;
}
```

`@C` 用在 `foreign func` 上时含义不变（声明一个由仓颉导入的 C 函数）；用在结构体上时含义不变（声明 C 兼容布局）。本提案只是为“`@C` 修饰一个有函数体的顶层函数”这一此前受限的形态赋予“导出为 C 可调用符号”的新含义。

修改建议：导出为 C 可调用符号这个含义原本就已经事实做到，只是不能自动生成头文件

### `@C[cName]` 自定义符号名

默认导出的 C 符号名等于仓颉函数的基本名。可通过命名参数自定义，以避免与 C 侧既有符号冲突或满足命名规范：

```cangjie
@C[cName: "demo_add"]
public func add(a: Int64, b: Int64): Int64 { a + b }
```

生成头文件中将以 `demo_add` 作为函数名。该机制对应 SE-0495 的 `@c(mirrorCName)`。

修改建议：重命名需求很常见，但一开始设计就引入需要一个无法规避的场景。

### 扩展可用类型

在导出函数签名与 `CFunc` 中，除现有 `CType` 外，第一版额外允许以下仓颉原生类型，并为其定义确定的 C 表示（详见[类型映射](#类型映射)）：

* `String` —— 映射为 `{ const char* data; size_t len; }` 的借用视图。
* `Array<T> where T <: CType` —— 映射为 `{ T* data; size_t len; }` 的借用视图。

仓颉引用类型（`class`）的不透明句柄传递列入[未来方向](#未来方向)，不在第一版范围内。


### 编译期自动生成头文件

新增编译开关 `--emit-c-header <path>`（并由 `cjpm` 暴露为构建选项），编译期为当前包内所有 `@C` 导出函数生成一份 C 头文件，内容包括：所需的标准头包含、扩展类型的 C 结构体定义、每个导出函数的 C 声明，以及一个可选的显式初始化函数声明。该机制对应 Go 的 `_cgo_export.h` 与 Swift 的 compatibility header。

### 隐藏运行时加载过程

每个导出函数都会获得一个由编译器生成的 C ABI **跳板（wrapper）**。跳板在被首次调用时，通过一次性守卫（once-guard）惰性完成运行时初始化与包初始化，随后把实际调用调度到协程上执行并同步返回结果。`InitCJRuntime`、`LoadCJLibraryWithInit`、`FindCJSymbol`、`RunCJTask`、`GetTaskRet`、名称改编等细节都不再出现在 C 调用方代码中。

需要自定义堆/GC/并发参数的高级用户，可在首次调用任何导出函数之前，显式调用生成的 `CJ_<module>_init(const RuntimeParam*)` 完成一次带参初始化；若未显式调用，则采用默认参数惰性初始化。

下图给出整体架构：C 调用方只接触自动生成的头文件与跳板符号，编译期产物与运行时封装把名称改编、运行时初始化、协程调度全部隐藏起来。

![C 调用仓颉整体架构](arch.svg)

## 详细设计

### 语法

* 复用属性 `@C`，使其可修饰**顶层、有函数体、非泛型**的函数，表示“导出为 C 可调用函数”。
* `@C` 接受一个可选命名参数 `cName: String`，指定导出的 C 符号名；缺省时取仓颉函数基本名。
* 被 `@C` 导出的函数应为 `public`，以保证其符号在编译单元外可见。

属性的合法修饰目标因此扩展为：`foreign func`（仓颉调 C，原有）、`struct`（C 兼容布局，原有）、顶层有体函数（C 调仓颉，**本提案新增**）。

### 导出函数的类型检查

导出函数的参数与返回类型必须可在 C 中表示。编译器对其签名施加如下检查，接受：

* 标准库基础数值类型：`Int8/16/32/64`、`UInt8/16/32/64`、`IntNative`、`UIntNative`、`Float32`、`Float64`、`Bool`。
* `Unit`（仅作返回类型，映射为 C `void`）。
* `CString`、`CPointer<T>`、`@C struct`。
* 使用 C 调用约定的函数引用 `CFunc<(...)->...>`。
* **本提案新增**：`String`、`Array<T> where T <: CType`。

拒绝：仓颉 `class`/接口存在体、`Option<T>` 等可空非指针类型、未标 `@C` 的结构体、泛型类型形参。这些限制与现有 `CFunc`/`@C struct` 的类型检查一致，仅在其上叠加对 `String`/`Array` 的放行。

### 类型映射

| 仓颉类型 | C 表示 | 传递语义 |
| --- | --- | --- |
| `Int8 … Int64` / `UInt8 … UInt64` | `int8_t … int64_t` / `uint8_t … uint64_t` | 值拷贝 |
| `IntNative` / `UIntNative` | `intptr_t` / `uintptr_t` | 值拷贝 |
| `Float32` / `Float64` | `float` / `double` | 值拷贝 |
| `Bool` | `bool`（`stdbool.h`） | 值拷贝 |
| `Unit`（返回） | `void` | —— |
| `CString` | `const char*` | 透传 |
| `CPointer<T>` | `T*` | 透传 |
| `@C struct S` | C `struct S` | 内存布局一致，值拷贝 |
| `CFunc<(A)->R>` | `R (*)(A)` | C 函数指针 |
| `String` | `CJString { const char* data; size_t len; }` | 借用视图，调用期间有效 |
| `Array<T> where T <: CType` | `CJArray_T { T* data; size_t len; }` | 借用视图，调用期间有效 |

`String` 与 `Array` 采用**借用**语义：跳板在调用期间通过 `acquireArrayRawData` 之类的机制固定底层缓冲并暴露其指针与长度，调用返回后视图即失效。C 侧若需在调用结束后继续持有数据，必须自行拷贝。该约束与 Go `_GoString_`/`GoSlice` 不可被 C 长期持有的规则一致。

### 头文件生成规则

对下例：

```cangjie
@C[cName: "demo_add"]
public func add(a: Int64, b: Int64): Int64 { a + b }

@C
public func greet(name: String): Unit { println("hi, ${name}") }

@C
public func sum(xs: Array<Int64>): Int64 { /* ... */ }
```

`cjc --emit-c-header demo.h demo.cj` 生成：

```c
/* demo.h — 由 cjc 自动生成，请勿手工修改。 */
#ifndef CJ_DEMO_H
#define CJ_DEMO_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 仓颉 String 的借用视图（调用期间有效，不可长期持有）。 */
typedef struct { const char* data; size_t len; } CJString;

/* 仓颉 Array<Int64> 的借用视图。 */
typedef struct { int64_t* data; size_t len; } CJArray_Int64;

/* 可选：自定义运行时参数的显式初始化；不调用则首次调用时按默认参数惰性初始化。 */
int CJ_demo_init(const void* /* RuntimeParam* */ param);

int64_t demo_add(int64_t a, int64_t b);
void    greet(CJString name);
int64_t sum(CJArray_Int64 xs);

#ifdef __cplusplus
}
#endif

#endif /* CJ_DEMO_H */
```

生成规则要点：

* 头文件仅打印 C 可解析内容，可被 C、C++ 编译器包含；C++ 下以 `extern "C"` 包裹。
* 仅当某扩展类型被实际用到时，才打印对应的 `CJString`/`CJArray_T` 定义，避免冗余。
* 头文件由现有的 `cjc` 头文件相关开关触发，并经 `cjpm` 暴露为包级构建选项。

### 运行时封装与初始化时序

每个 `@C` 导出函数，编译器生成两部分产物：

1. 一个**未改编的 C ABI 符号**（跳板），即头文件中声明的那个函数；
2. 跳板内部对真实仓颉函数体的调用。

跳板的执行流程：

```text
C 调用 demo_add(1, 2)
  └─ 跳板: 一次性守卫（pthread_once / std::call_once 语义）
        ├─ 已初始化? 否 → InitCJRuntime(默认或 CJ_demo_init 传入的参数)
        │                 → 包初始化（package_global_init）
        └─ 已初始化? 是 → 跳过
  └─ 跳板: 将实参打包，经协程调度执行仓颉函数体（RunCJTask）
  └─ 跳板: 等待并取回结果（GetTaskRet），释放句柄（ReleaseHandle）
  └─ 返回 int64_t 给 C 调用方
```

* **惰性初始化**：默认无需 C 侧任何显式初始化调用；一次性守卫保证多线程下仅初始化一次。
* **显式初始化（可选）**：C 侧可在首次调用前调用 `CJ_<module>_init(&param)` 以自定义堆大小、GC、并发与日志参数；该调用同样受一次性守卫保护，重复调用安全。
* **协程调度透明**：仓颉函数体在协程（cjthread）上执行的事实对 C 调用方不可见，跳板以同步语义返回。

下图给出 C 首次调用一个导出函数的完整时序，首次调用触发一次性初始化，后续调用直接进入协程调度：

![C 首次调用导出函数的时序](sequence.svg)

### 所有权与生命周期

* **数值/`@C struct`/指针**：按值或按指针透传，所有权语义与现有 FFI 一致。
* **`String`/`Array` 入参**：借用语义。底层缓冲在调用期间被固定，跳板返回后视图失效；C 侧需长期持有时必须拷贝。
* **返回 `String`/`Array`**：第一版不支持返回这两类引用型聚合（其底层为受 GC 管理的仓颉堆对象，跨调用边界返回需要句柄化生命周期管理）。需要返回字符串/数组数据时，约定由调用方传入 `CPointer<T>` 输出缓冲，或将该能力推迟到[未来方向](#未来方向)的句柄机制。

## 源码兼容性

本提案完全向后兼容，所有新增能力均为可选启用：

* 对 `foreign func`、`@C struct` 的现有用法行为不变。
* `@C` 修饰顶层有体函数此前是受限/无导出语义的形态，赋予其新含义不影响既有可编译代码。
* 不写 `@C` 的普通仓颉函数行为完全不变，不会产生额外的 C 符号。

## ABI 兼容性

* `@C` 导出函数发出单个使用 C 调用约定的未改编符号。
* 在函数上增删 `@C` 是 ABI 破坏性变更（增删了一个 C 符号）；修改 `cName` 同样是 ABI 破坏性变更（符号名变化）。
* 扩展类型的 C 表示（`CJString`/`CJArray_T` 的字段布局）一经确定即构成 ABI 约定，其字段顺序与类型不可随意更改。
* 生成的跳板与初始化逻辑对更早版本的运行时保持后向兼容：跳板只依赖 `Cangjie.h` 已稳定导出的运行时接口。

## 对采用的影响

* 采用方只需为待导出函数加 `@C`，并在构建中开启 `--emit-c-header`，即可获得可 `#include` 的 C 接口，无需改动 C 侧的运行时编排代码。
* 现有手工调用 `Cangjie.h` 的 C 宿主可渐进迁移：新函数走 `@C` 导出，旧路径保持可用，二者可共存。

## 未来方向

* **不透明引用句柄。** 为仓颉 `class`/引用类型引入 `CJObjectRef`（不透明 `void*`）与句柄表，配合显式 `retain`/`release`，使 C 侧可安全地长期持有仓颉对象。这对应 SE-0495 提出的 `@c` struct “opaque data” 方向与 Go 的 `runtime/cgo.Handle`。
* **返回引用型聚合。** 在句柄机制就绪后，支持以句柄化生命周期返回 `String`/`Array`。
* **`@C @implementation` 等价物。** 允许仓颉函数实现一个在手写 C 头中声明的函数，由编译器校验声明与实现签名一致，从而支持自定义调用约定等场景。
* **自定义调用约定。** 在导出函数上支持指定 C 调用约定（如 `stdcall`），以满足特定回调 API 的要求。

## 备选方案

* **新增独立属性（如 `@CExport`）而非复用 `@C`。** 可使“导出”语义更直白，但会让 C 互操作分裂为两个属性、增加心智负担。复用 `@C` 与现有“仓颉调 C”同源，与 SE-0495 复用 `@objc`/引入 `@c` 的取舍一致，故选择扩展 `@C`。
* **强制显式初始化（要求 C 侧先调 `CJ_init()`）。** 语义更显式，但把运行时编排重新推回给用户，与“隐藏加载过程”的目标相悖。本提案以惰性自动初始化为默认，并保留显式初始化作为可选调优入口。
* **沿用 `Cangjie.h` 底层接口、仅补文档。** 不引入语言机制，成本最低，但无法解决“无稳定契约、无头文件、无类型校验、与现有 FFI 割裂”的根因，调用方负担依旧。
* **仅放行 `CType`、不扩展 `String`/`Array`。** 实现最简，但用户仍需在最常用类型上手工桥接，违背降低使用门槛的初衷。

## 参考资料

* [Swift SE-0495: C compatible functions and enums](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0495-cdecl.md)
* [Go 命令文档：cgo（`//export`、`_cgo_export.h`、`_GoString_`、传指针规则）](https://pkg.go.dev/cmd/cgo)
* 仓颉运行时对外 C 接口：`runtime/src/Cangjie.h`（`InitCJRuntime` / `LoadCJLibraryWithInit` / `FindCJSymbol` / `RunCJTask` / `GetTaskRet` / `FiniCJRuntime` / `package_global_init`）
* 仓颉标准库 `CType` 定义：`stdlib/libs/std/core/c_type.cj`
* [仓颉 C 互操作开发指南](https://cangjie-lang.cn/docs?url=https%3A%2F%2Fcj-docs.gitcode.com%2Fzh%2F1.1.3%2Fdev-guide%2Fsource_zh_cn%2FFFI%2Fcangjie-c.html)
* [仓颉语言规范 第 13 章 互操作](https://cangjie-lang.cn/docs?url=%2F0.53.18%2FSpec%2Fsource_zh_cn%2FChapter_13_Interop%28zh%29.html)
