计划针对业界的中间IR进行一个调研：
主要如下几个目的：
1、有哪些基于源码生成的编程语言IR？
2、这些IR的特点有哪些？是否支持多语言？是高层级还是较低层级？高层及可能保留面向对象语义，底层级更追求指令等优化。
3、IR的主要目的是什么？编译器优化、设计模式识别、代码转换等等

当前有一个初步的分析内容：
汇总之后做个总结汇报

IR名称	类型/来源	所属项目/机构	设计目标与关键特点	支持的主要语言/领域
LLVM IR	工业标准	LLVM	通用、SSA形式的低层IR，是众多编译器后端的事实标准。	C/C++, Rust, Swift, Kotlin等
MLIR	工业/学术	LLVM基金会	多层级IR，核心思想是通过“方言”支持不同抽象级别。	通用，尤其适合AI和异构计算
GIMPLE	工业标准	GCC	GCC中端使用的三地址码IR。	C, C++, Fortran等GCC支持的语言
GENERIC	工业标准	GCC	GCC前端生成的语言无关高层IR。	C, C++, Fortran等GCC支持的语言
RTL	工业标准	GCC	GCC后端使用的、非常接近汇编语言的低层IR。	目标机器指令生成
Java Bytecode	工业标准	Oracle / JVM	JVM执行的栈式字节码。	Java, Kotlin, Scala, Groovy等
CIL / MSIL	工业标准	Microsoft / .NET	.NET平台的通用中间语言。	C#, F#, VB.NET等
WebAssembly	工业标准	W3C	为浏览器设计的栈式虚拟机字节码。	C/C++, Rust, Go等
SPIR-V	工业标准	Khronos Group	用于表示图形着色器和计算内核的二进制IR。	OpenCL, Vulkan, OpenGL
Dalvik Bytecode	工业标准	Android	Android Dalvik VM使用的寄存器式字节码。	Java（Android平台）
MAPLE IR	工业	华为 (OpenArkCompiler)	为多语言联合编译优化设计的IR。	Java, C/C++, JavaScript等
Panda IR	工业	华为 (ArkCompiler)	鸿蒙方舟编译器的中间表示。	多语言（OpenHarmony生态）
WHIRL	工业	Open64	具有5个抽象层次的多级IR。	C, C++, Fortran等
Swift SIL	语言专属	Apple	为Swift设计，包含高层语义信息的SSA形式IR。	Swift
Rust MIR	语言专属	Rust项目	Rust的中级IR，用于借用检查等安全分析。	Rust
Rust HIR	语言专属	Rust项目	Rust的高层IR，是抽象语法树的进一步结构化表示。	Rust
Kotlin IR	语言专属	JetBrains	Kotlin编译器实现多平台后端的IR。	Kotlin
Jimple	学术/框架	Soot框架	Soot框架中用于Java字节码分析的、无栈的三地址码IR。	Java (Soot框架)
Baf	学术/框架	Soot框架	Soot框架中基于栈的、最接近字节码的IR。	Java (Soot框架)
Shimple	学术/框架	Soot框架	Soot框架中Jimple的SSA（静态单赋值）形式。	Java (Soot框架)
Grimp	学术/框架	Soot框架	Soot框架中Jimple的聚合版本，用于简化表达式。	Java (Soot框架)
WALA IR	学术/框架	WALA	WALA分析框架中基于SSA的、方法粒度的IR。	Java (WALA框架)
SUIF IR	学术	斯坦福大学	用于编译器研究的中间格式。	C
CompCert IRs	学术	CompCert项目	经过形式化验证的C编译器使用的多种IR。	C (安全关键领域)
COINS HIR/MIR/LIR	学术	COINS项目	编译器研究框架中定义的高、中、低三层IR。	多种语言 (研究用)
Graal IR	学术/工业	Oracle Labs	基于图的“节点之海”IR，用于Java JIT编译器。	Java/GraalVM
LARA Virtual AST	学术	LARA框架	用于多语言设计模式检测的高层虚拟AST。	Java, C/C++等
EIR (ELVM IR)	学术/开源	ELVM项目	极简指令集（6个寄存器）的IR，旨在统一60+种语言。	多种语言（含深奥语言）
SPIRAL IR	学术/开源	个人项目	分层渐进式架构，包含AIR→CIR→EIR→LIR四层。	通用
HLO / XLA IR	特定领域	TensorFlow	XLA编译器的高层操作IR，用于优化机器学习计算图。	机器学习 (TensorFlow)
Relay IR	特定领域	TVM	TVM中用于表示和优化深度学习模型的高层函数式IR。	深度学习 (TVM)
TensorIR	特定领域	TVM	TVM中用于表示和优化底层张量程序的核心IR。	深度学习 (TVM)
CUDA Tile IR	特定领域	NVIDIA	基于MLIR，用于GPU上Tile计算优化的IR。	GPU编程 (NVIDIA CUDA)
vISA IR	特定领域	Intel	专为Intel GPU架构设计的、介于LLVM IR和汇编之间的IR。	GPU编程 (Intel)
HSAIL / BRIG	特定领域	HSA基金会	用于异构系统架构的中间语言，BRIG是其二进制形式。	异构计算 (HSA)
OpenCL IR	特定领域	Khronos Group	基于LLVM IR，为OpenCL内核添加了特定元数据。	OpenCL
TREE IR	经典形式	-	用树形结构表示程序的经典IR。	通用
DAG IR	经典形式	-	用有向无环图表示表达式，可共享公共子表达式。	通用
三地址码 (TAC)	经典形式	-	每条指令最多三个操作数的经典IR形式。	通用
SSA形式	经典形式	-	每个变量只赋值一次的IR形式，是众多现代IR的基础。	通用
后缀表示	经典形式	-	将操作符置于操作数之后的简单IR形式。	通用

💎 总结
这份列表展示了IR生态的多样性。从服务于特定语言编译器的语言专属IR（如Swift SIL），到作为通用优化和代码生成基础的工业标准IR（如LLVM IR），再到为特定领域（如深度学习）设计的专用IR，每种IR都在其设计目标下达到了最佳平衡。

这个清单力求全面，但IR领域仍在持续发展，新的IR和方言（尤其在MLIR生态中）不断涌现。希望这份更完整的清单能为你提供有价值的参考。

