# 仓颉调用 C：内存安全边界与改进机会

> **结论先行**：仓颉已经用 `CType`/`@C` 约束布局类型，用 `unsafe` 标记 C 调用、指针读写和数组借用，并提供 `isNull()`、`@CallingConv`、`inout` 有效期规则及 GWP-Asan 抽样检测；这些能力能暴露风险、约束部分误用，但不能证明 C 实现、手写声明、长度、所有权或生命周期正确。Rust、Swift、Go 的原始 C 指针边界同样需要显式契约，差异主要在安全封装和工具链成熟度，不宜简单判定谁“天然安全”。

## 一、范围、版本与证据

本报告只分析**仓颉代码调用 C**：`foreign func`/`CFunc` 声明与调用、C 数据布局、原始指针、字符串、数组及 `inout`。不讨论 C 通过 `Cangjie.h` 调仓颉，也不把仓颉函数导出给 C 纳入结论。

- 文档基线：`cangjie_docs` 1.1 分支的《仓颉与 C 互操作》与运行时环境文档。
- 实测 SDK：Cangjie Compiler `1.1.0-beta.10 (cjnative)`，目标 `x86_64-w64-mingw32`。
- 实测链路：Clang 构建 Windows C DLL；`cjc` 编译、链接并运行仓颉调用端，退出码为 0。

“需要 `unsafe`”只表示开发者主动承担前置条件，并不自动验证这些条件；报告据此区分**风险显式化**与**风险消除**。

## 二、仓颉已有防线及其边界

| 设施 | 已提供的约束 | 仍需人工保证 |
|---|---|---|
| `CType` / `@C struct` | FFI 签名只接受 C 兼容类型；字段也受 `CType` 约束 | C 头文件与仓颉声明是否一致；packed、位域、联合体、平台 ABI |
| `unsafe` | `foreign`/`CFunc` 调用、指针读写/偏移、数组借用可见 | 指针是否有效、长度是否正确、释放者是谁、C 是否保存借用地址 |
| `CPointer<T>` | 有泛型元素类型、`isNull()`、显式读写/偏移 | 不携带长度、生命周期与所有权；类型转换仍可误用 |
| `CString` | 可判空、测长、复制为 `String`；`mallocCString`/`free` 有明确路径 | 编码、终止符、来源与释放器契约 |
| `VArray<T,$N>` | 长度进入类型；调用时以 `inout` 传址 | C 声明和 `$N` 必须一致；C 不得越界或保存地址 |
| `@CallingConv` | 支持 `CDECL`、`STDCALL`，默认 CDECL | 必须与 C 侧完全一致；不是所有平台 ABI 都由该标记覆盖 |
| GWP-Asan | Linux/OpenHarmony 对数组借用做抽样 canary 与未释放检测 | 非全量、非 Windows；不能代替契约和测试 |

## 三、风险全景

### 3.1 ABI 与声明漂移

`CType` 检查的是“仓颉类型是否可用于 C ABI”，不是“手写声明是否等于真实头文件”。以下错误仍可能越过编译器：

- `int64_t` 被声明为 `Int32`，造成参数/返回值解释错误；
- C 使用 `#pragma pack`、位域、联合体或柔性数组，而仓颉按普通 `@C struct` 表达；
- C 的 `size_t`/`long` 等平台相关类型被写成固定但错误的宽度；
- 调用约定不一致。仓颉并非“不支持调用约定”：应使用 `@CallingConv[CDECL|STDCALL]`，但双方仍须一致；
- 头文件演进后，手写 `foreign` 声明未同步。

**改进重点**：优先由头文件生成绑定并在 CI 做头文件漂移检测、`sizeof`/`alignof`/字段偏移断言，而不是仅依赖 `@C`。

### 3.2 指针、可空性与所有权

`CPointer<T>` 可以直接表示空指针，`CPointer<T>()` 创建 null，`isNull()` 判空；因此问题不是“没有 Option 就不能判空”，而是 C 函数签名无法强制调用方检查。`Option<CPointer<T>>`、Swift Optional 与 Rust `Option<NonNull<T>>` 更适合安全包装层，却通常不能直接替代原始 C ABI 参数。

主要风险：

1. C 返回 null，仓颉未先 `isNull()` 就读写；
2. C 释放后仓颉继续持有，形成 use-after-free；
3. 两侧对释放责任理解不同，造成 double-free 或泄漏；
4. `CPointer<T>` 不带长度，错误的索引或偏移造成越界；
5. `CPointer` 间显式转换允许把同一地址按错误类型解释；
6. 分配器不配对，例如 C 自定义 allocator 的结果被交给 `LibC.free`。

**安全包装建议**：原始 `foreign` 声明保持 ABI 形态；对上层暴露可空返回、拥有型 `Resource`、借用型回调以及 `(pointer, length)`/复制后的 `Array`，集中执行判空和释放。

### 3.3 仓颉堆数组借给 C

真实 API 是 `acquireArrayRawData<T>(array)` 与 `releaseArrayRawData(handle)`。前者返回 handle，传给 C 的地址是 `handle.pointer`。两者均要求 `unsafe`，且必须配对。

```cangjie
let handle = acquireArrayRawData(values)
try {
    use_buffer(handle.pointer, values.size)
} finally {
    releaseArrayRawData(handle)
}
```

风险不是普通 `Array.append` 后“realloc 使裸指针自然失效”这么简单；acquire/release 协议用于固定/借用托管数组。真正需要明确的是：

- release 前 C 只能在约定范围访问；
- C 不得在调用结束或 release 后保存和使用 `handle.pointer`；
- C 不得 `free` 该地址；
- 长度必须单独传递且双方单位一致；
- 异常、提前返回也必须执行 release；
- C 越界写仍可能破坏仓颉堆。

仓颉文档提供的 GWP-Asan 可在 Linux/OpenHarmony 抽样发现部分越界写及未 release，但它不是全量证明。

### 3.4 `inout`：调用期间有效的地址

`inout` 是**调用点修饰符**，不是参数类型写法。它只可用于 `CFunc` 调用，把可变、满足 `CType` 的变量临时形成 `CPointer<T>`；字面量、`let`、入参、临时表达式和源自 class 实例成员的值受限制。文档明确：该地址**仅在函数调用期间保证有效**，C 不应保存。

```cangjie
foreign func write_value(p: CPointer<Int32>): Unit
var value: Int32 = 0
unsafe { write_value(inout value) }
```

这与 Swift `withUnsafePointer`/`withUnsafeMutablePointer` 的闭包借用目标相近：都要求指针不逃逸，但 C 仍可违规保存。Rust 在安全引用内部有借用检查；一旦降为 `*mut T` 并进入 `unsafe` FFI，C 是否保存和何时使用也依赖契约。Go cgo 还施加“C 不能在调用返回后保留 Go 指针”等运行时规则。四者都不能证明任意 C 实现遵约。

### 3.5 字符串、回调、并发和错误边界

- `CString` 是以 NUL 结尾的 C 字符串视图；`toString()` 会复制，但编码和来源必须约定。仓颉 `String` 传 C 应用 `LibC.mallocCString` 并在 `finally` 中 `LibC.free`。
- `CFunc` 回调不能捕获变量，但函数指针强转、回调上下文指针与注销时机仍可能造成悬垂。
- 仓颉线程可能恢复到不同 OS 线程；C 的 TLS、线程亲和性、长时间阻塞和进程退出语义可能与预期冲突。
- C 的错误码、`errno`、部分初始化和异常/longjmp 不应跨边界泄漏；包装层要把它们转换成明确结果并执行清理。

## 四、可运行的 E2E 案例

C 动态库：

```c
#include <stdint.h>
__declspec(dllexport) void write_value(int32_t *p) { if (p) *p = 42; }
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

本机验证结果：C DLL 编译成功；仓颉代码编译链接成功；程序退出码 `0`。该案例同时验证了 `foreign func`、`unsafe`、`inout`、数组 handle 的 `.pointer`、长度传递与 `finally` 配对释放。

## 五、竞品校验：相同维度、同一标尺

| 维度 | 仓颉 | Rust | Swift | Go/cgo |
|---|---|---|---|---|
| 布局声明 | `CType` + `@C struct`；仍需与头文件一致 | `#[repr(C)]` 固定 Rust 类型布局；仍需声明与头文件一致 | Clang importer 导入 C 声明；手工 raw layout 仍有风险 | cgo 从 C 声明生成桥接；跨平台类型仍需注意 |
| 原始指针生命周期 | `CPointer` 不追踪生命周期 | `*const/*mut` 不受 borrow checker 自动保护 | `UnsafePointer` 不追踪生命周期 | `unsafe.Pointer` 不追踪生命周期，另有 cgo 指针规则 |
| 可空性 | null `CPointer` + `isNull()`；可在包装层转 Option | raw pointer 可 null；常在包装层用 `Option<NonNull<T>>` | imported C pointer 常呈 Optional；解包后仍是 unsafe pointer | nil pointer 可表达；仍需主动检查 |
| 越界/长度 | `CPointer` 不带长度；`VArray` 或 pointer+len | raw pointer 不带长度；安全层可构造 slice | raw pointer 不带长度；可用 BufferPointer 包装 | raw pointer 不带长度；Go slice 只在 Go 侧带 len/cap |
| 堆借用 | acquire/release 均为 unsafe，handle 固定数组 | 暴露 raw pointer 进入 unsafe；需保证底层不移动与不释放 | `withUnsafe*` 限定词法作用域；C 仍可能错误保存 | cgo 规则限制 C 保留 Go 指针；常复制到 C 内存 |
| 栈地址 | `inout` 仅调用期间有效 | 借用转 raw pointer 后，FFI 合同仍需 C 遵守 | `withUnsafe*` 闭包期间有效 | 调用期规则与运行时检查更强，但 C 仍需遵约 |
| unsafe 标记 | 调用、指针操作、数组 acquire/release 均显式 | FFI 调用/解引用依具体版本和声明进入 unsafe | 类型名/操作体现 Unsafe，但无 Rust 式 unsafe 块体系 | `unsafe` 包使转换显式，调用 C 函数本身不等于静态证明 |
| 绑定生成 | 官方 HLE `cj-c2cj`；社区 cjbind 可处理 C/C++ 包装 | bindgen/cbindgen 生态成熟 | Clang importer 为主 | cgo 由 preamble/头文件生成桥接 |

### 六项质疑的直接回答

1. **`#[repr(C)]` 与 `@C`**：二者都约束本语言结构的 C 兼容布局；都不会校验它是否匹配某个外部头文件。仓颉还通过 `CType` 限定可用字段类型；Rust 可配合 bindgen/layout tests，生态更成熟不等于 raw ABI 自动安全。
2. **`CPointer` 与 `UnsafePointer`**：二者都是不带生命周期的原始指针抽象；Swift 的优势主要来自 importer、Optional 呈现和 `withUnsafe*` 作用域 API，不能据此称 `UnsafePointer` 本身更安全。
3. **Option/Optional**：Swift importer 常把 nullable C pointer 映射为 Optional；Rust `Option<NonNull<T>>` 常用于包装且有 niche 优化，但 `Option<*mut T>` 不应被无条件当作 C ABI 指针；仓颉 raw 边界使用可为 null 的 `CPointer` 与 `isNull()`，可在安全包装层转 Option。
4. **堆内存暴露与 unsafe**：仓颉 acquire/release 和 Rust raw-pointer 路径都显式 unsafe；unsafe 只标记责任。Swift/Go 的作用域或运行时规则更强，但 C 若越界或保存借用地址仍可破坏安全。
5. **栈地址**：仓颉 `inout`、Swift `withUnsafeMutablePointer`、Rust 临时借用转 `*mut` 都能把地址交给 C；共同底线是不得逃逸约定的有效期。
6. **自动绑定**：仓颉并非只有手写声明，官方文档包含 HLE `cj-c2cj`，社区有 cjbind。与成熟竞品的主要差距是覆盖面、稳定性、布局回归和 CI 生态，而不是“完全没有工具”。

## 六、机会与落地顺序

1. **先做可执行契约**：生成绑定、layout tests、符号/调用约定检查、真实 C DLL E2E。
2. **建立安全包装层**：raw `foreign` 仅在内部；外部使用 `Resource`、Option、复制型数组/字符串和 pointer+len。
3. **作用域借用 API**：为数组提供类似 `withArrayRawData` 的闭包封装，在 `finally` 自动 release，减少遗漏并表达“不逃逸”。
4. **所有权元数据**：在绑定描述中记录 borrowed/owned、nullable、length-of、allocator/deallocator，并据此生成包装。
5. **检测工具**：Linux/OpenHarmony 启用 GWP-Asan；各平台结合 C ASan、模糊测试、并发和异常路径测试。
6. **文档模板**：每个 FFI 函数必须写清 ABI、可空性、长度单位、线程、有效期、释放者和错误契约。

## 七、最终判断

仓颉 C-FFI 不是“毫无保护的裸 C”：它已有类型资格约束、unsafe 边界、判空、调用约定、调用期 `inout` 规则、数组 acquire/release 协议和检测设施。其核心缺口也不是单一语法，而是**手写声明无法自动对应头文件，原始指针不携带长度/生命周期/所有权，安全包装和验证工具链尚需系统化**。竞品在原始指针边界有相同根本限制；可借鉴之处集中在导入器、作用域 API、所有权注解和持续验证，而非简单照搬红绿优劣结论。
