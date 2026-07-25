# 业界中间表示（IR）调研报告

> 调研基准：2026 年 7 月
> 研究对象：由源码、字节码或上一级程序表示生成，供编译、分析、转换、验证、执行或硬件映射使用的中间表示

## 1. 分类口径

| 分类 | 记录范围 | 代表项 |
|---|---|---|
| 多语言编译基础设施 | 多个源码前端共享的优化或代码生成表示；可承载多种方言的基础设施 | LLVM IR、MLIR、GCC GENERIC/GIMPLE/RTL、Graal IR、Maple IR |
| 多语言运行时格式 | 多种语言编译到同一字节码或虚拟指令格式 | JVM bytecode、.NET CIL、WebAssembly |
| 单语言多后端 IR | 一种源语言通过共享 IR 连接多个目标平台 | Kotlin Backend IR |
| 语言专属 IR | 保存特定语言语义，服务该语言的检查、优化和生成 | Swift SIL、Rust HIR/MIR、Kotlin FIR |
| 程序分析、转换与验证表示 | 面向调用图、指针、数据流、插桩、源码转换、二进制提升或验证 | Soot Jimple、WALA IR、P-code、VEX、CompCert IR |
| 领域 IR | 面向 AI、张量、GPU、shader 或异构硬件 | StableHLO、XLA HLO、TVM Relax/TensorIR、CUDA Tile IR、SPIR-V、vISA |
| 历史与研究 IR | 官方资料或归档仓仍可核验的编译器研究表示 | WHIRL、SUIF、COINS HIR/LIR、ELVM EIR、HSAIL/BRIG、SPIR |

SSA、三地址码、Tree、DAG、CFG、栈式和寄存器式属于表示结构或性质，不作为具体项目 IR 名称。

## 2. 多语言 IR 与共享用途

“多语言”按公开接口分为四类：多个语言前端生成同一 IR、多个语言生成同一运行时格式、一种语言通过共享 IR 生成多个后端、基础设施通过方言承载不同语言或领域表示。

### 2.1 多个源码前端共享优化与后端

| IR | 所属项目 | 结构或层级 | 公开语言覆盖 | 公开用途 | 来源 |
|---|---|---|---|---|---|
| LLVM IR | LLVM | 类型化 SSA + CFG，目标无关 | Clang、Rust、Swift 等编译器可生成 LLVM IR | 优化、AOT/JIT、目标代码生成 | [LLVM LangRef](https://llvm.org/docs/LangRef.html) |
| GCC GENERIC | GCC | 语言无关树形表示 | GCC 前端将各语言语法树转换为 GENERIC | 连接前端与 GIMPLE | [GCC GENERIC](https://gcc.gnu.org/onlinedocs/gccint/GENERIC.html) |
| GCC GIMPLE | GCC | 三地址表示，可使用 SSA | GCC 支持的多个语言前端 | 目标无关优化、数据流分析 | [GCC GIMPLE](https://gcc.gnu.org/onlinedocs/gccint/GIMPLE.html) |
| GCC RTL | GCC | 机器相关寄存器传送表示 | 由 GCC 中端向各目标后端生成 | 指令选择、调度、寄存器分配、代码生成 | [GCC RTL](https://gcc.gnu.org/onlinedocs/gccint/RTL.html) |
| Graal StructuredGraph / LIR | GraalVM | 节点图下降至低层 IR | JVM bytecode；官方文档列出 JavaScript、Python、Ruby 等 Truffle 语言 | JIT 编译、内联、逃逸分析、去虚化、机器码生成 | [Graal Compiler](https://www.graalvm.org/latest/reference-manual/java/compiler/) |
| Maple IR | OpenArkCompiler / MapleCompiler | 多层文本 IR | 官方设计文档列出 C、C++、Java、JavaScript | 编译优化、跨语言链接、代码生成 | [Maple IR Design](https://github.com/openmaple/MapleCompiler/blob/master/doc/en/MapleIRDesign.md) |

### 2.2 多方言、多层级基础设施

| IR | 所属项目 | 扩展单位 | 语言或领域输入 | 公开用途 | 来源 |
|---|---|---|---|---|---|
| MLIR | LLVM | Dialect、Operation、Type、Attribute、Conversion | 官方清单包含 GPU、LLVM、SPIR-V、TOSA、Tensor、Vector 等方言 | 定义多层表示、方言转换、Pass 基础设施 | [MLIR LangRef](https://mlir.llvm.org/docs/LangRef/)、[Dialects](https://mlir.llvm.org/docs/Dialects/) |
| CIR | LLVM/Clang | MLIR 方言 | C、C++ | 在 Clang AST 与 LLVM IR 之间表示 C/C++ 语义 | [ClangIR](https://llvm.github.io/clangir/) |
| ONNX-MLIR | ONNX-MLIR | ONNX、Krnl 等 MLIR 方言 | ONNX 模型 | 模型导入、优化和目标代码生成 | [ONNX-MLIR](https://github.com/onnx/onnx-mlir) |
| Torch-MLIR | LLVM | Torch、Linalg 等 MLIR 方言 | PyTorch 模型 | PyTorch 图导入与下层方言转换 | [Torch-MLIR](https://github.com/llvm/torch-mlir) |

### 2.3 多语言运行时格式

| 格式 | 执行模型 | 公开语言覆盖 | 公开用途 | 来源 |
|---|---|---|---|---|
| JVM bytecode | 有类型栈机、局部变量槽、类文件元数据 | Java、Kotlin、Scala、Groovy 等 JVM 语言 | 类加载验证、解释、JIT/AOT 执行 | [JVMS](https://docs.oracle.com/javase/specs/jvms/se26/html/) |
| .NET CIL / IL | 栈式 CLI、CTS 类型系统和元数据 | C#、F#、Visual Basic 等 .NET 语言 | 程序集分发、验证、JIT/AOT 执行 | [ECMA-335](https://ecma-international.org/publications-and-standards/standards/ecma-335/) |
| WebAssembly | 低层抽象栈机、结构化控制流、线性内存 | C/C++、Rust、Go 等工具链可生成 Wasm | Web、WASI、插件和嵌入式运行时 | [WebAssembly Core](https://github.com/WebAssembly/spec)、[WASI](https://wasi.dev/) |

### 2.4 单语言共享多后端

| IR | 所属项目 | 源语言 | 目标后端 | 公开用途 | 来源 |
|---|---|---|---|---|---|
| Kotlin Backend IR | Kotlin | Kotlin | JVM、JavaScript、Native、WebAssembly | 后端共享 lowering 与代码生成基础设施 | [Kotlin IR Overview](https://github.com/JetBrains/kotlin/blob/master/compiler/ir/ReadMe.md) |

## 3. 语言专属 IR

| IR | 位置与结构 | 保存的信息 | 公开用途 | 来源 |
|---|---|---|---|---|
| Swift SIL | Swift AST 与 LLVM IR 之间；SSA + CFG | Swift 类型、所有权、泛型、witness table、vtable、调用约定 | 初始化与所有权检查、ARC 优化、去虚化、泛型优化 | [Swift SIL](https://github.com/swiftlang/swift/blob/main/docs/SIL/SIL.md) |
| Rust HIR | 宏展开与名称解析后的高层树 | 声明、泛型、表达式和类型检查输入 | 类型检查、trait 分析、生成 THIR/MIR | [Rust HIR](https://rustc-dev-guide.rust-lang.org/hir.html) |
| Rust MIR | 完全类型化 CFG；statement + terminator | Place、move、borrow、drop、显式控制流 | 借用检查、数据流分析、优化、常量求值、代码生成准备 | [Rust MIR](https://rustc-dev-guide.rust-lang.org/mir/index.html) |
| Kotlin FIR | Kotlin K2 前端 IR | 声明、解析状态、类型推断信息 | 语义分析、诊断、IDE 分析接口 | [Kotlin FIR](https://github.com/JetBrains/kotlin/tree/master/compiler/fir) |

## 4. 程序分析、转换与验证 IR

### 4.1 源码与字节码分析、转换

| IR / 程序模型 | 输入 | 结构 | 公开用途 | 来源 |
|---|---|---|---|---|
| Soot Jimple | JVM bytecode、Android DEX | 有类型、无栈三地址码 | 调用图、数据流、指针分析、插桩和转换 | [Soot](https://github.com/soot-oss/soot)、[SootUp](https://soot-oss.github.io/SootUp/latest/) |
| Soot Shimple | Jimple | Jimple 的 SSA 形式 | SSA 数据流分析 | [Soot Shimple](https://soot-oss.github.io/soot/docs/4.3.0/options/soot_options.html) |
| Soot Baf | Jimple | 接近 JVM 的栈式表示 | 字节码转换与生成 | [Soot](https://github.com/soot-oss/soot) |
| Soot Grimp | Jimple | 聚合表达式表示 | 反编译和可读输出 | [Soot](https://github.com/soot-oss/soot) |
| WALA IR | Java bytecode 等 WALA 前端输入 | 方法级 SSA 寄存器传送表示 | 调用图、指针分析、切片和数据流分析 | [WALA IR API](https://wala.github.io/javadoc/com/ibm/wala/ssa/IR.html) |
| Clava 程序模型 | C/C++ 源码 | Clang AST 上的 joinpoint API | 源码查询、变换和再生成 | [Clava](https://github.com/specs-feup/clava) |
| CompCert IR 家族 | C | Clight、Cminor、RTL、LTL、Mach 等多级表示 | 带操作语义的编译转换和正确性证明 | [CompCert Documentation](https://compcert.org/doc/) |

### 4.2 二进制提升与机器码分析

| IR | 输入 | 结构 | 公开用途 | 状态与来源 |
|---|---|---|---|---|
| Ghidra P-code | 处理器机器指令 | 由操作码与 varnode 构成的寄存器传送语言；支持 raw p-code 与带 SSA 信息的 high p-code | 反汇编语义建模、仿真、数据流图和反编译分析 | Ghidra 当前表示；[P-code Reference](https://ghidra.re/ghidra_docs/languages/html/pcoderef.html)、[Decompiler Analysis Engine](https://ghidra.re/ghidra_docs/languages/html/sleigh.html) |
| VEX IR | 多种处理器机器码 | 类型化临时值、表达式、语句与 IRSB 基本块 | Valgrind 动态插桩；angr 使用 pyvex 将机器码提升为统一表示进行跨体系结构分析 | Valgrind 与 angr 使用；[Valgrind VEX](https://valgrind.org/docs/manual/writing-tools.html#writing-tools.vex)、[angr IR](https://docs.angr.io/en/latest/advanced-topics/ir.html) |
| BAP IR / BIL | 二进制文件和机器指令 | BAP 以架构无关 IR 表示程序；BIL 是其传统指令语言 | 控制流图恢复、程序分析、符号执行和插件处理 | BAP 当前文档使用 IR；BIL 见语言参考；[BAP Handbook](https://binaryanalysisplatform.github.io/bap/api/master/bap/Bap/index.html)、[BIL Language](https://binaryanalysisplatform.github.io/bap/api/master/bap/Bap/Std.html#module-Bil) |
| REIL | 机器指令 | 精简指令集形式的中间语言 | BinNavi 的静态代码分析与二进制代码分析 | BinNavi 仓库已归档并停止主动开发；[BinNavi](https://github.com/google/binnavi)、[REIL Reference](https://github.com/google/binnavi/blob/master/src/main/java/com/google/security/zynamics/reil/README.txt) |

### 4.3 源码规范化表示

| IR | 输入 | 结构 | 公开用途 | 来源 |
|---|---|---|---|---|
| CIL（C Intermediate Language） | ANSI C，以及多数 GNU C 和 Microsoft C 扩展 | 保留类型和源码关系的高层表示；将循环、返回、类型转换等归约为较少的核心构造，并可同时承载 AST 与 CFG 信息 | C 程序分析、数据流分析、源码到源码转换和全程序处理 | [CIL Documentation](https://people.eecs.berkeley.edu/~necula/cil/) |

### 4.4 图式程序模型

| 程序模型 | 输入 | 结构 | 公开用途 | 来源 |
|---|---|---|---|---|
| Code Property Graph（CPG） | Joern 各语言前端生成的程序信息 | 带类型节点、带标签有向边和键值属性的有向多重图；在同一结构中保存语法、控制流和过程内数据流，并可通过 overlay 表示其他抽象层 | 跨视图图查询、程序模式检索和漏洞发现 | [Joern CPG Documentation](https://docs.joern.io/code-property-graph/)、[CPG Specification](https://cpg.joern.io/) |

CPG 是图式程序模型，不是指令序列式编译 IR。Joern 文档将其称为所支持语言之间的统一中间程序表示。

### 4.5 验证语言与程序模型

| 表示 | 输入或前端 | 结构 | 公开用途 | 来源 |
|---|---|---|---|---|
| Boogie IVL | Dafny、VCC、SMACK、GPUVerify 等前端 | 面向验证的过程式语言，包含类型、全局声明、表达式、过程及结构化或非结构化实现 | 作为程序验证器的中间层；Boogie 工具生成验证条件并交给 SMT 求解器 | [Boogie Documentation](https://boogie-docs.readthedocs.io/en/latest/)、[Microsoft Research](https://www.microsoft.com/en-us/research/project/boogie-an-intermediate-verification-language/) |
| WhyML | Why3 输入及其支持的其他输入格式 | 模块化规范与程序语言，包含逻辑声明、程序类型、可变状态、循环、异常、前后置条件和循环不变式 | 生成验证条件并调用 SMT 求解器或交互式证明器；也可直接编写带契约的程序 | [WhyML Language](https://www.why3.org/doc/whyml.html)、[Why3 VC Generators](https://www.why3.org/doc/vcgen.html) |

### 4.6 代表性学术记录

| 对象 | 论文 | 作者 | 载体与年份 | 索引记录 |
|---|---|---|---|---|
| CIL | *CIL: Intermediate Language and Tools for Analysis and Transformation of C Programs* | George C. Necula、Scott McPeak、Shree P. Rahul、Westley Weimer | Compiler Construction，2002 | [DOI: 10.1007/3-540-45937-5_16](https://doi.org/10.1007/3-540-45937-5_16) |
| Code Property Graph | *Modeling and Discovering Vulnerabilities with Code Property Graphs* | Fabian Yamaguchi、Nico Golde、Daniel Arp、Konrad Rieck | IEEE Symposium on Security and Privacy，2014 | [DOI: 10.1109/SP.2014.44](https://doi.org/10.1109/SP.2014.44) |
| Boogie | *Boogie: A Modular Reusable Verifier for Object-Oriented Programs* | Mike Barnett、Bor-Yuh Evan Chang、Robert DeLine、Bart Jacobs、K. Rustan M. Leino | Formal Methods for Components and Objects，2006 | [DOI: 10.1007/11804192_17](https://doi.org/10.1007/11804192_17) |

## 5. 字节码与虚拟指令格式

| 格式 | 所属平台 | 结构 | 公开用途 | 来源 |
|---|---|---|---|---|
| Android DEX | Android Runtime | 寄存器式指令与 `.dex` 文件格式 | Android 类、方法、字段、类型、异常和注解的运行时表示 | [DEX Format](https://source.android.com/docs/core/runtime/dex-format) |
| ARK bytecode | OpenHarmony Runtime Core | `.pa` 文本汇编与 `.abc` 二进制 | OpenHarmony Runtime Core 的字节码文件、解释和编译输入 | [Runtime Core](https://github.com/openharmony/arkcompiler_runtime_core) |
| ELVM EIR | ELVM | 六寄存器低层指令集 | ELVM C 前端与多个实验性后端之间的表示 | [ELVM](https://github.com/shinh/elvm) |

DEX 是 Android 文件格式和指令载体；Dalvik 是 Android 早期运行时，ART 是当前 Android Runtime。ARK bytecode 的 `.pa`、`.abc` 与 Runtime Core 内部编译 IR 是不同表示。

## 6. AI、GPU 与异构计算 IR

| IR | 所属项目或标准 | 层级 | 公开用途 | 来源 |
|---|---|---|---|---|
| StableHLO | OpenXLA | 基于 MLIR 的稳定算子集合 | 机器学习框架与编译器之间的版本化交换 | [StableHLO Spec](https://github.com/openxla/stablehlo/blob/main/docs/spec.md) |
| XLA HLO | OpenXLA/XLA | 计算图和算子 IR | XLA 内部图优化、布局和后端编译 | [XLA Architecture](https://openxla.org/xla/architecture) |
| TVM Relax | Apache TVM | 图级、函数式张量 IR | 模型导入、图变换、算子融合和下层 TensorIR 调用 | [TVM Relax](https://tvm.apache.org/docs/deep_dive/relax/index.html) |
| TVM TensorIR | Apache TVM | 循环、buffer 和张量程序表示 | 张量程序变换、调度和硬件映射 | [TVM TensorIR](https://tvm.apache.org/docs/deep_dive/tensor_ir/index.html) |
| TVM Relay | Apache TVM | 函数式图级 IR | TVM 早期模型表示；当前架构文档以 Relax 和 TensorIR 为主要函数表示 | [TVM Architecture](https://tvm.apache.org/docs/arch/index.html) |
| SPIR-V | Khronos | 二进制 shader/compute IR | Vulkan、OpenCL 等环境与驱动之间的交换和执行输入 | [SPIR-V Registry](https://registry.khronos.org/SPIR-V/) |
| CUDA Tile IR | NVIDIA | 基于 MLIR 的 tile-oriented IR | tiled computation、GPU 内存层级和 Tensor Core 编译 | [CUDA Tile](https://github.com/NVIDIA/cuda-tile) |
| Intel vISA | Intel Graphics Compiler | GPU 虚拟指令集 | 高层编译器与 vISA finalizer 之间的设备编译接口 | [vISA Specification](https://github.com/intel/intel-graphics-compiler/tree/master/documentation/visa) |

StableHLO 是版本化交换表示，XLA HLO 是 XLA 编译器内部表示。OpenCL SPIR 基于特定 LLVM bitcode 版本；SPIR-V 是 Khronos 当前维护的二进制中间语言标准。

## 7. 历史与研究型 IR

| IR | 项目 | 公开语言或输入 | 公开用途 | 状态与来源 |
|---|---|---|---|---|
| WHIRL | Open64 | C、C++、Fortran | 多层编译优化和代码生成 | 社区仓可访问；[Open64](https://github.com/open64-compiler/open64) |
| SUIF1 / SUIF2 | Stanford SUIF | C 等研究前端 | 循环、并行化、依赖分析和编译器研究 | 历史项目；[SUIF](https://suif.stanford.edu/) |
| COINS HIR/LIR | COINS | C、Fortran | 高层分析、并行化和低层代码生成 | 历史项目；[COINS](http://coins-compiler.osdn.jp/) |
| HSAIL / BRIG | HSA Foundation | 异构计算输入 | HSAIL 文本格式及其二进制表示 BRIG | 官方归档仓可访问；[gccbrig](https://github.com/HSAFoundation/gccbrig) |
| OpenCL SPIR | Khronos | OpenCL C | OpenCL 到 LLVM bitcode 的标准映射 | 历史规范；[SPIR](https://www.khronos.org/spir/) |

## 8. 开源托管平台仓库记录

| 平台 | 仓库 | 身份或页面声明 | 地址 |
|---|---|---|---|
| GitHub | LLVM、Swift、Rust、Kotlin、Graal、Soot、WALA、TVM、StableHLO、CUDA Tile | 对应项目官网或官方组织指向的主仓 | [llvm/llvm-project](https://github.com/llvm/llvm-project)、[swiftlang/swift](https://github.com/swiftlang/swift)、[rust-lang/rust](https://github.com/rust-lang/rust)、[JetBrains/kotlin](https://github.com/JetBrains/kotlin)、[oracle/graal](https://github.com/oracle/graal)、[soot-oss/soot](https://github.com/soot-oss/soot)、[wala/WALA](https://github.com/wala/WALA)、[apache/tvm](https://github.com/apache/tvm)、[openxla/stablehlo](https://github.com/openxla/stablehlo)、[NVIDIA/cuda-tile](https://github.com/NVIDIA/cuda-tile) |
| GitLab | MOPSA Analyzer | 项目官网指向的源码仓 | [mopsa/mopsa-analyzer](https://gitlab.com/mopsa/mopsa-analyzer) |
| GitLab | Free Pascal Compiler | Free Pascal 开发页指向的源码仓 | [freepascal.org/fpc/source](https://gitlab.com/freepascal.org/fpc/source) |
| GitLab | Clash Compiler | 页面声明为 GitHub 主仓的 CI 镜像 | [clash-lang/clash-compiler](https://gitlab.com/clash-lang/clash-compiler) |
| Gitee | OpenArkCompiler | OpenArkCompiler 组织仓 | [openarkcompiler/OpenArkCompiler](https://gitee.com/openarkcompiler/OpenArkCompiler) |
| Gitee | LLVM Project | `mirrors` 名空间镜像 | [mirrors/llvm-project](https://gitee.com/mirrors/llvm-project) |
| GitCode | LLVM、ONNX-MLIR、Torch-MLIR | 页面标注 GitHub 上游或镜像加速 | [LLVM](https://gitcode.com/GitHub_Trending/ll/llvm-project)、[ONNX-MLIR](https://gitcode.com/gh_mirrors/on/onnx-mlir)、[Torch-MLIR](https://gitcode.com/gh_mirrors/to/torch-mlir) |

## 9. 来源索引

- 通用编译基础设施：[LLVM](https://llvm.org/docs/LangRef.html)、[MLIR](https://mlir.llvm.org/docs/LangRef/)、[GCC internals](https://gcc.gnu.org/onlinedocs/gccint/)、[GraalVM](https://www.graalvm.org/latest/reference-manual/java/compiler/)、[Maple IR](https://github.com/openmaple/MapleCompiler/blob/master/doc/en/MapleIRDesign.md)
- 语言专属 IR：[Swift SIL](https://github.com/swiftlang/swift/blob/main/docs/SIL/SIL.md)、[Rust HIR/MIR](https://rustc-dev-guide.rust-lang.org/)、[Kotlin IR](https://github.com/JetBrains/kotlin/blob/master/compiler/ir/ReadMe.md)
- 运行时格式：[JVMS](https://docs.oracle.com/javase/specs/jvms/se26/html/)、[ECMA-335](https://ecma-international.org/publications-and-standards/standards/ecma-335/)、[WebAssembly](https://github.com/WebAssembly/spec)、[Android DEX](https://source.android.com/docs/core/runtime/dex-format)、[OpenHarmony Runtime Core](https://github.com/openharmony/arkcompiler_runtime_core)
- 分析与验证：[Soot/SootUp](https://soot-oss.github.io/SootUp/latest/)、[WALA](https://wala.github.io/javadoc/com/ibm/wala/ssa/IR.html)、[Clava](https://github.com/specs-feup/clava)、[CompCert](https://compcert.org/doc/)、[CIL](https://people.eecs.berkeley.edu/~necula/cil/)、[Joern CPG](https://docs.joern.io/code-property-graph/)、[Boogie](https://boogie-docs.readthedocs.io/en/latest/)、[Why3](https://www.why3.org/doc/)
- AI 与 GPU：[StableHLO](https://github.com/openxla/stablehlo)、[XLA](https://openxla.org/xla/architecture)、[TVM](https://tvm.apache.org/docs/arch/index.html)、[SPIR-V](https://registry.khronos.org/SPIR-V/)、[CUDA Tile](https://github.com/NVIDIA/cuda-tile)、[Intel vISA](https://github.com/intel/intel-graphics-compiler/tree/master/documentation/visa)
