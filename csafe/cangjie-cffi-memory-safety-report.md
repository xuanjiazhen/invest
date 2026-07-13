# 仓颉 C-FFI 内存安全问题现状分析

> 基于仓颉 1.1.3 版本 C 互操作能力，全面梳理仓颉→C 双向 FFI 边界上的内存安全风险。

---

## 一、分析背景与范围

仓颉当前提供两套 C 互操作机制：

| 方向 | 机制 | 关键设施 |
|------|------|----------|
| C → 仓颉（声明） | `foreign` 声明 + `CFunc` + `@C` struct | `CPointer<T>`、`CString`、`CType` 约束 |
| 仓颉 → C（导出） | `@C` 导出函数（提案 CJ-0001） | 自动生成头文件 + runtime stub |
| 运行时桥接 | `Cangjie.h` 底层接口 | `InitCJRuntime`、`FindCJSymbol`、`RunCJTask` |

**分析范围**：边界类型映射、指针生命周期、堆/栈内存暴露、竞品安全措施对照。

---

## 二、内存安全问题分类

### 2.1 ABI 不一致：互操作边界类型映射错误

**问题本质**：仓颉类型与 C 类型之间的映射由开发者手工保证，编译器仅做有限校验（`CType` trait），无法在编译期检测所有 ABI 不匹配。

#### 案例 2.1.1：整型宽度不匹配

```cangjie
// C 侧声明：int32_t add(int32_t a, int32_t b);
foreign func add(a: Int32, b: Int32): Int32  // ✅ 正确

// 错误：C 侧实际是 int64_t，但仓颉声明为 Int32
foreign func add(a: Int32, b: Int32): Int32  // ❌ ABI 不匹配，栈破坏
```

当 C 侧实际参数为 8 字节 `int64_t`，仓颉侧按 4 字节 `Int32` 压栈/读取时，会导致参数错位、返回值截断，严重时栈帧破坏。

#### 案例 2.1.2：结构体对齐与填充

```cangjie
@C
struct S {
    var a: Int8   // offset 0
    var b: Int64  // offset 8（仓颉按自然对齐填充 7 字节）
}

// C 侧若用 #pragma pack(1) 或不同对齐策略，offset 将不一致
```

仓颉 `@C` struct 采用 C 语言自然对齐规则，但当 C 代码使用 `__attribute__((packed))` 或跨平台编译（32/64 位）时，对齐差异导致字段偏移错误。

#### 案例 2.1.3：`CFunc` 调用约定不匹配

```cangjie
// C 侧：typedef void (*callback)(int);  // 默认 cdecl
// 仓颉侧：
var cb: CFunc<(Int32) -> Unit> = ... // 默认假设 cdecl
// 若 C 侧实际为 stdcall/fastcall，调用约定不匹配，栈失衡
```

当前 `CFunc` 不支持显式指定调用约定（`stdcall`、`fastcall` 等），在 Windows 平台上尤其危险。

#### 案例 2.1.4：`CString` 编码假设

```cangjie
// C 侧返回 UTF-8 字符串
foreign func getName(): CString

// 仓颉侧直接构造 String
let s = String(getName())  // 假设 UTF-8，若 C 侧为 Latin-1/GBK 则乱码或崩溃
```

`CString` ↔ `String` 转换默认假定 UTF-8，无编码协商机制，多语言环境下的字符串边界是隐式炸弹。

---

### 2.2 指针安全问题

#### 2.2.1 悬垂指针：C 侧释放后仓颉侧继续使用

```cangjie
// C 侧分配，仓颉侧持有
foreign func createData(): CPointer<Int32>
foreign func freeData(p: CPointer<Int32>): Unit

main() {
    let p = createData()
    freeData(p)          // C 侧 free
    let v = p[0]         // ❌ use-after-free，未定义行为
}
```

仓颉语言没有 Rust 的 borrow checker，`CPointer<T>` 不携带任何生命周期信息。C 侧释放后，仓颉侧持有的 `CPointer` 自动成为悬垂指针，编译器无感知。

#### 2.2.2 双重释放

```cangjie
let p: CPointer<UInt8> = malloc(100)
// ... 仓颉侧使用
free(p)
// ... 跨 FFI 返回给 C 侧后，C 侧再次 free(p)  ❌ double-free
```

仓颉和 C 之间无所有权转移机制。同一块内存在边界两侧分别释放，导致 double-free。

#### 2.2.3 空指针解引用

```cangjie
foreign func mayReturnNull(): CPointer<Int64>

main() {
    let p = mayReturnNull()
    // p 可能为 null（C 侧 NULL），但仓颉侧无 Option<CPointer<T>>
    let v = p[0]  // ❌ 空指针解引用，段错误
}
```

当前 `CPointer<T>` 没有 `Option<CPointer<T>>` 的惯用表达，C 侧返回 NULL 时仓颉侧无编译期强制检查。

#### 2.2.4 数组越界

```cangjie
foreign func getArray(): CPointer<Int32>
// C 侧：int arr[10]; return arr;

main() {
    let p = getArray()
    for (i in 0..100) {  // ❌ 不知道实际长度
        process(p[i])
    }
}
```

`CPointer<T>` 不携带长度信息，C 侧数组的长度约定无法传递到仓颉侧。任何对 C 数组的遍历都依赖程序员手动维护长度，极易越界。

#### 2.2.5 指针运算错误

```cangjie
let p: CPointer<UInt8> = getBuffer()
let offset: Int64 = getOffset()  // 可能为负数或超大值
let q = p + offset  // ❌ 无边界检查，可读/写任意内存
```

`CPointer` 的算术运算不做任何边界校验，攻击者可通过控制 offset 实现任意地址读写。

---

### 2.3 仓颉堆内存暴露到 C 侧

仓颉通过 `acquire` 系列 API 将托管堆上的内存原始指针暴露给 C 侧，这是最危险的内存安全边界之一。

#### 2.3.1 `acquireRawData`：String 的底层指针暴露

```cangjie
let s = "Hello, 仓颉"
let raw = acquireRawData(s)  // 返回 CPointer<UInt8>，指向 GC 堆
// C 侧收到 raw 后：
//   - 若在 GC 回收 s 后继续使用 raw → use-after-free
//   - 若对 raw 调用 free() → 破坏 GC 堆
//   - 若修改 raw 内容 → 破坏 String 不可变性
```

`acquireRawData` 将 GC 管理的内存地址暴露给无 GC 意识的 C 代码。**该指针的生命周期与原始 `String` 对象绑定**，但 C 侧无法感知 GC 何时回收。

#### 2.3.2 `acquireArrayRawData`：Array 的底层缓冲区暴露

```cangjie
var arr = [1, 2, 3, 4, 5]
let raw = acquireArrayRawData(arr)  // CPointer<Int32>，指向托管堆

// 危险场景 1：GC 触发后
// arr 不再被引用 → GC 回收 → raw 悬垂

// 危险场景 2：Array 扩容
arr.append(6)  // 可能触发 realloc → raw 指向旧缓冲区
```

`Array` 的底层缓冲区可能在 GC 回收、扩容 realloc 后失效。`acquireArrayRawData` 获取的指针是**瞬时的**，C 侧必须"用完即弃"。

#### 2.3.3 `acquire` + `release` 配对遗漏

```cangjie
// 仓颉侧分配，手动管理生命周期
let p: CPointer<UInt8> = acquire(ptr) // 增加引用计数
// ... 传递给 C 侧使用 ...
// 忘记调用 release(ptr)  → 内存泄漏
```

`acquire`/`release` 配对依赖程序员纪律，无 RAII 或编译期检查。在复杂控制流（异常、提前返回）下极易遗漏 `release`。

#### 2.3.4 C 侧长期持有仓颉堆指针

```cangjie
// 仓颉侧注册回调
func onData(callback: CFunc<(CPointer<UInt8>) -> Unit>) {
    let buf = acquireArrayRawData(globalBuffer)
    callback(buf)  // buf 传给 C 侧回调
    // 若 C 侧将 buf 保存为全局变量 → 函数返回后 buf 失效
}
```

任何从仓颉堆获取的原始指针，其有效期不超过持有引用的函数的生命周期。当 C 侧将指针保存为全局变量或在线程间传递时，将导致严重的内存安全问题。

---

### 2.4 仓颉栈内存暴露到 C 侧

#### 2.4.1 `inout` 参数暴露栈地址

```cangjie
foreign func readIntoBuffer(buf: CPointer<Int32>, len: Int32): Unit

func processData() {
    var buf = Array<Int32>(100, item: 0)
    var raw = acquireArrayRawData(buf)
    readIntoBuffer(raw, 100)  // C 侧写入 buf
    // buf 在栈上？在堆上？取决于编译器优化
}
```

当仓颉变量被编译器决定分配在栈上时，通过 `acquireArrayRawData` 或 `inout` 暴露给 C 侧的地址是栈地址。C 侧若将此地址保存并在函数返回后使用，就是典型的 **栈上 use-after-return**。

#### 2.4.2 栈缓冲区溢出

```cangjie
foreign func strcpy(dst: CPointer<UInt8>, src: CString): Unit

func vulnerable() {
    var buf = Array<UInt8>(16, item: 0)
    let raw = acquireArrayRawData(buf)
    let longStr = "This is a very very long string..."
    strcpy(raw, longStr)  // ❌ 溢出 16 字节缓冲区
}
```

当仓颉侧分配的缓冲区小于 C 侧写入的数据时，`CPointer` 不提供任何边界保护，直接导致栈/堆缓冲区溢出。

---

### 2.5 C 语言经典安全问题在仓颉 FFI 中的投射

| C 经典问题 | 仓颉 FFI 中的体现 | 编译器防护 |
|-----------|------------------|-----------|
| Use-after-free | C 侧 free → 仓颉侧 `CPointer` 仍可用 | ❌ 无 |
| Double-free | 两侧各 free 一次 | ❌ 无 |
| 空指针解引用 | `CPointer` 无 Option 语义 | ❌ 无 |
| 缓冲区溢出 | `CPointer` 无边界信息 | ❌ 无 |
| 格式化字符串 | 无对应机制 | N/A |
| 整数溢出 | `Int32`/`Int64` 在 FFI 边界的截断 | ❌ 无 |
| 类型混淆 | `CPointer<T>` 的 reinterpret cast | ❌ 无 |
| 竞态条件 | 多线程访问 `CPointer` | ❌ 无 |

---

## 三、竞品安全措施对照

| 能力 | Swift | Go (cgo) | Rust | 仓颉现状 |
|------|-------|----------|------|----------|
| **编译期类型映射校验** | ✅ `@c` 编译期校验类型布局 | ⚠️ cgo 生成桥接代码，类型检查在 Go 侧 | ✅ `#[repr(C)]` + 编译期对齐检查 | ⚠️ `CType` trait 约束，手工映射 |
| **指针生命周期** | ✅ `UnsafePointer` 显式 unsafe | ⚠️ `unsafe.Pointer` 无生命周期 | ✅ borrow checker + `unsafe` 块 | ❌ `CPointer<T>` 无生命周期 |
| **空指针安全** | ✅ `Optional<UnsafePointer>` | ⚠️ 运行时 panic（nil dereference） | ✅ `Option<*const T>` | ❌ `CPointer` 无 Option |
| **数组边界** | ✅ `UnsafeBufferPointer` 带 count | ⚠️ `GoSlice` 带 len/cap | ✅ `&[T]` / `slice` 带长度 | ❌ `CPointer` 不携带长度 |
| **堆内存暴露** | ✅ 需显式 `withUnsafe` 闭包 | ⚠️ `C.CBytes` 需手动 free | ✅ `unsafe` + 明确 unsafe 语义 | ⚠️ `acquireRawData` 暴露 GC 指针 |
| **栈内存暴露** | ✅ `withUnsafe` 闭包保证生命周期 | ⚠️ cgo 会 pin 住 Go 指针 | ✅ borrow checker 编译期保证 | ❌ 无保护机制 |
| **所有权转移** | ✅ ARC + `Unmanaged` 手动 retain/release | ⚠️ 需手动 `C.free` | ✅ 编译期所有权 | ❌ 全手动 |
| **自动头文件生成** | ✅ `swiftc -emit-c-header` | ✅ `go build -buildmode=c-shared` | ✅ `cbindgen` 工具 | ⚠️ 提案阶段（CJ-0001） |

---

## 四、风险等级汇总

| 类别 | 风险等级 | 典型后果 | 缓解难度 |
|------|---------|---------|----------|
| ABI 不匹配 | 🔴 高 | 栈破坏、crash、数据损坏 | 中（需编译器校验） |
| use-after-free | 🔴 高 | 任意代码执行、crash | 高（需生命周期系统） |
| Double-free | 🔴 高 | 堆破坏、crash | 中（需所有权模型） |
| 空指针解引用 | 🟡 中 | 段错误 | 低（加 Option 语义） |
| 数组越界 | 🔴 高 | 任意读写、信息泄漏 | 中（需携带长度） |
| acquire 泄漏 | 🟡 中 | 内存泄漏 | 低（RAII 包装） |
| 栈地址暴露 | 🔴 高 | use-after-return、代码执行 | 高（需编译期分析） |
| 缓冲区溢出 | 🔴 高 | 栈破坏、代码执行 | 中（需边界传递） |
| 类型混淆 | 🟡 中 | 逻辑错误、数据损坏 | 中（加强类型系统） |

---

## 五、结论

仓颉 C-FFI 当前的内存安全态势可以概括为：

1. **"信任程序员"模型**：所有安全检查都依赖程序员手动保证，编译器不提供 FFI 边界的内存安全防护。
2. **`acquire` 系列 API 是最大风险点**：将 GC 托管内存的原始指针暴露给 C 侧，无生命周期追踪，极易产生 use-after-free。
3. **`CPointer<T>` 缺乏语义信息**：不携带长度、不表达可空性、无所有权标记，本质上是 C 语言 `T*` 的薄封装。
4. **与竞品差距显著**：Swift 的 `withUnsafe` 闭包生命周期、Rust 的 borrow checker、Go cgo 的指针 pinning 都是有效的安全措施，仓颉均尚未对齐。
5. **CJ-0001 提案是正确方向**：通过自动生成头文件和 stub 代码封装运行时，可消除部分手工错误，但未解决 `CPointer` 和 `acquire` 的根本安全问题。

**建议优先投入方向**：
- 为 `CPointer<T>` 增加编译期生命周期标注或至少 borrow scope
- `acquire` 系列 API 改为闭包形式（`withRawData`），自动管理指针有效期
- `CPointer<T>` 支持 `Option` 语义，空指针编译期检查
- 引入 `CBuffer<T>` 类型，携带长度和容量信息
- 编译期对齐检查，消除 ABI 不匹配隐患
