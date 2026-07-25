# 业界中间表示（IR）调研需求

计划针对业界的中间 IR 进行调研，主要目的如下：

1. 调研有哪些由源码生成的编程语言中间表示（IR）。
2. 分析这些 IR 的特点，包括是否支持多语言、抽象层级，以及高层 IR 对面向对象等语言语义的保留程度与低层 IR 对指令级优化的支持能力。
3. 分析 IR 的主要用途，包括编译器优化、静态分析、设计模式识别、代码转换、运行时执行、异构计算等。
4. 对现有初步清单进行查证、筛选和归类，形成可用于总结汇报的调研材料。
5. 收集资料时，除通用网页检索外，还需在 GitHub、GitLab、Gitee、GitCode 等主要开源代码托管平台进行专项检索，关注项目实现、文档、活跃状态和可复用能力。

## 初步调研清单

| IR 名称 | 类型/来源 | 所属项目/机构 | 初步设计目标与特点 | 初步支持语言/领域 |
|---|---|---|---|---|
| LLVM IR | 工业标准 | LLVM | 通用、SSA 形式的低层 IR，是众多编译器后端的事实标准 | C/C++、Rust、Swift、Kotlin 等 |
| MLIR | 工业/学术 | LLVM | 多层级 IR，通过方言支持不同抽象级别 | 通用，尤其适合 AI 和异构计算 |
| GIMPLE / GENERIC / RTL | 工业标准 | GCC | 分别覆盖 GCC 中端、语言无关高层和低层机器相关表示 | GCC 支持的语言与目标机器 |
| Java Bytecode | 工业标准 | JVM | JVM 执行的栈式字节码 | Java、Kotlin、Scala、Groovy 等 |
| CIL / MSIL | 工业标准 | .NET | .NET 平台的通用中间语言 | C#、F#、VB.NET 等 |
| WebAssembly | 工业标准 | W3C | 面向可移植执行环境的栈式虚拟机指令格式 | C/C++、Rust、Go 等 |
| SPIR-V | 工业标准 | Khronos Group | 图形着色器与计算内核的二进制中间语言 | Vulkan、OpenCL、OpenGL 等 |
| Dalvik Bytecode | 工业标准 | Android | Dalvik VM 使用的寄存器式字节码 | Android Java 生态 |
| MAPLE IR | 工业 | OpenArkCompiler | 面向多语言联合编译与优化 | Java、C/C++ 等 |
| Panda IR | 工业 | ArkCompiler Runtime Core | 面向多语言运行时的字节码与编译表示 | OpenHarmony 多语言生态 |
| WHIRL | 工业 | Open64 | 多抽象层次的编译器 IR | C、C++、Fortran 等 |
| Swift SIL | 语言专属 | Swift | 保留 Swift 语义的 SSA IR | Swift |
| Rust HIR / MIR | 语言专属 | Rust | 分别服务于高层语义分析和借用检查、优化、代码生成 | Rust |
| Kotlin IR | 语言专属 | Kotlin | 统一 Kotlin 多平台后端 | Kotlin |
| Soot IR 家族 | 学术/框架 | Soot | Jimple、Shimple、Baf、Grimp 等面向 Java 分析与转换 | Java/JVM |
| WALA IR | 学术/框架 | WALA | 基于 SSA 的方法级程序分析表示 | Java 等 |
| SUIF IR | 学术 | Stanford SUIF | 编译器研究基础设施 | C 等 |
| CompCert IR 家族 | 学术 | CompCert | 形式化验证编译链中的多级 IR | C |
| COINS HIR/MIR/LIR | 学术 | COINS | 编译器研究框架中的高、中、低层表示 | 研究用途 |
| Graal IR | 工业/研究 | GraalVM | 基于图的 JIT 编译 IR | Java/GraalVM 语言 |
| LARA Virtual AST | 学术/框架 | LARA | 面向多语言源代码分析与转换的虚拟 AST | Java、C/C++ 等 |
| ELVM IR | 开源 | ELVM | 极简指令集，用于跨目标后端实验 | 多种语言与目标 |
| SPIRAL IR | 开源/研究 | SPIRAL | 分层渐进式中间表示 | 通用研究用途 |
| HLO / XLA IR | 特定领域 | OpenXLA | 机器学习计算图与算子优化 | 机器学习 |
| Relay / TensorIR | 特定领域 | Apache TVM | 分别表达高层模型与底层张量程序 | 深度学习 |
| CUDA Tile IR | 特定领域 | NVIDIA | 面向 GPU Tile 计算的 MLIR 方言/表示 | GPU 编程 |
| vISA | 特定领域 | Intel | Intel GPU 虚拟指令集 | GPU 编程 |
| HSAIL / BRIG | 特定领域 | HSA Foundation | 异构系统的文本与二进制中间语言 | 异构计算 |
| Tree / DAG / TAC / SSA / 后缀表示 | 经典形式 | 通用理论 | 常见 IR 结构或性质，不等同于单一项目 IR | 通用 |

## 预期输出

- 一份调研计划，明确边界、分类框架、检索方法和交付件。
- 一份正式调研报告，包含结论、IR 图谱、代表性 IR 对比、用途分析、开源托管平台专项检索结果、选型建议和可追溯参考资料。
- 一份基于报告的交互式 HTML 幻灯片，用于总结汇报。
- 将幻灯片加入仓库首页索引。