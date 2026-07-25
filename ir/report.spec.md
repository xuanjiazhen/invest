# 业界中间表示（IR）调研报告

> 调研基准：2026 年 7 月
> 研究对象：由源码、字节码或上一级程序表示生成，供编译、分析、转换、验证、执行或硬件映射使用的中间表示

## 1. 执行摘要

中间表示不是一种格式，而是一组围绕“在什么阶段保留哪些语义、为谁提供操作接口”形成的工程设计。现代编译器很少依赖单一 IR 完成全部任务，主流路径是让高层表示保留类型、对象、泛型、所有权或张量等领域语义，再逐层下降到控制流、内存、寄存器和目标指令。

本次调研得到六项核心结论：

1. **IR 层级是相对位置，不是统一刻度。** LLVM IR 常被称为低层 IR，但仍保留类型、函数、SSA 和 CFG；GCC RTL、Graal LIR、CompCert Mach 等表示才更接近机器层。
2. **多层 IR 是主流架构。** GCC 使用 GENERIC/GIMPLE/RTL，Rust 使用 HIR/THIR/MIR，Swift 在 AST 与 LLVM IR 之间设置 SIL，CompCert 使用带形式化语义的多级链路。
3. **多语言有三种不同含义。** LLVM/GCC 接收多个语言前端；JVM/.NET/Wasm 提供多语言可移植执行格式；MLIR 通过方言承载多个领域和抽象层级。三者不能只用“支持多语言”归为同类。
4. **高层语义决定分析和转换上限。** 面向借用检查、对象模型分析、设计模式识别或模型级图优化时，MIR、SIL、Jimple、Relax 等专用表示通常比 LLVM IR 更合适。
5. **交换格式与编译器内部 IR 的稳定性目标不同。** StableHLO、SPIR-V、JVM bytecode、CIL、Wasm 强调生产者与消费者之间的契约；XLA HLO、GIMPLE、SIL、MIR 等内部 IR 可随编译器演进。
6. **开源项目的主开发阵地高度集中于 GitHub。** GitLab 有少量可信主仓，Gitee 与 GitCode 的检索样本以镜像和加速分发为主；平台命中数不能直接代表项目成熟度。

## 2. IR 的边界与分类

### 2.1 什么可以称为 IR

IR 是编译或程序处理系统中的结构化程序表示。它至少具有明确的生产者、消费者和合法性约束，并支持一种或多种操作：分析、变换、优化、验证、解释、JIT/AOT 编译或序列化交换。

AST、HIR、字节码和虚拟 ISA 都可属于广义 IR，但侧重点不同：

| 类别 | 典型生产者 | 主要消费者 | 代表信息 |
|---|---|---|---|
| AST / 高层 IR | 解析器、语义分析器 | 类型检查、源码分析与转换 | 声明、作用域、对象模型、泛型、源位置 |
| 中层优化 IR | 高层 lowering | 优化器、数据流分析器 | CFG、SSA、显式调用与内存操作 |
| 低层 / 机器 IR | 指令选择或中端 lowering | 寄存器分配、调度、代码生成 | 寄存器、寻址、机器模式、指令约束 |
| 字节码 / 虚拟 ISA | 语言编译器 | 验证器、解释器、JIT/AOT | 稳定指令集、类型与运行时元数据 |
| 领域 IR | 框架前端或领域编译器 | 领域优化器、硬件后端 | 张量、算子、tile、shader、并行模型 |

### 2.2 不应作为独立项目 IR 并列的概念

SSA、三地址码、Tree、DAG、CFG、栈式和寄存器式是表示结构或性质。一个具体 IR 可以同时拥有多种性质，例如 SIL 是 SSA + CFG，GIMPLE 可进入 SSA 形式，MLIR Region 可表达 SSACFG 或图结构。它们适合作为比较维度，不适合作为与 LLVM IR、MIR 并列的项目名称。

### 2.3 核心权衡：语义密度与优化自由度

高层 IR 能直接表达“类、协议、所有权、张量、设备”等意图，便于语义分析与领域变换；低层 IR 将隐式语义展开为控制流、内存和指令，便于跨语言复用优化与映射硬件。典型链路如下：

```text
源码
  → AST / HIR：名称、类型、对象、泛型、源位置
  → 语言或领域 IR：所有权、调用、张量、异常、显式控制流
  → 通用优化 IR：SSA、CFG、数据流、内存操作
  → 机器 IR / 虚拟 ISA：寄存器、寻址、指令约束
  → 机器码，或稳定字节码供运行时消费
```

## 3. 代表性 IR 图谱

### 3.1 通用编译基础设施

| IR | 层级与结构 | 语言覆盖 | 主要目的 | 关键判断 | 状态 |
|---|---|---|---|---|---|
| LLVM IR | 低层、类型化 SSA + CFG | 多前端 | 通用优化、AOT/JIT、代码生成 | 对象模型和多数源码语义已消解；适合跨语言后端复用 | 活跃 |
| MLIR | 多层级、Operation/Region/Block/Value、可扩展方言 | 多语言、多领域 | 渐进 lowering、领域优化、编译器复用 | 是 IR 基础设施，不是固定语义的单体 IR | 活跃 |
| GCC GENERIC | 高层树形 | GCC 多前端 | 语言无关高层承接 | 保留声明、类型和结构化控制 | 活跃 |
| GCC GIMPLE | 中层三地址式，可转 SSA | GCC 多前端 | 中端分析与目标无关优化 | 含 High/Low GIMPLE，不是单一固定形态 | 活跃 |
| GCC RTL | 低层、机器相关节点表示 | GCC 后端 | 指令选择后优化、分配、调度与生成 | 高层语义基本消解 | 活跃 |
| WHIRL | 多层树形 | C/C++/Fortran | Open64 优化基础设施 | 产业地位偏历史，社区仓仍有小规模活动 | 有限维护 |
| CompCert IR 家族 | Clight 至 Mach/Asm 的多级表示 | C | 可验证优化与代码生成 | 各层具有操作语义，转换带语义保持证明 | 活跃、专用 |

**判断：** 若目标是构建可扩展、多层、跨领域编译基础设施，MLIR 的方言与 conversion 模型最有参考价值；若目标是复用成熟通用后端，LLVM IR 是最强接口；若需要研究完整传统编译链和机器相关下降，GCC 的三级体系最具代表性。

### 3.2 语言专属 IR

| IR | 位置与结构 | 保留的关键语义 | 主要任务 | 状态 |
|---|---|---|---|---|
| Swift SIL | Swift AST 与 LLVM IR 之间，SSA + CFG | lowered Swift types、所有权、泛型、witness/vtable、调用约定 | 初始化与所有权检查、去虚化、ARC 与泛型优化 | 活跃 |
| Rust HIR | 宏展开与名称解析后，高层树形 | 声明、泛型、大量源码结构 | 类型与 trait 相关分析、生成 THIR/MIR | 活跃 |
| Rust MIR | 完全类型化 CFG，statement + terminator | Place、move/borrow/drop、显式控制流 | 借用检查、数据流、优化、const eval、代码生成准备 | 活跃 |
| Kotlin FIR | Kotlin 前端 IR，接近源码 | 声明、类型推断与解析信息 | K2 前端语义分析 | 活跃 |
| Kotlin Backend IR | 中层树形、符号化 | Kotlin 类型、声明、类/函数/表达式 | JVM/JS/Native/Wasm 多后端共享 lowering 与生成 | 活跃 |
| Graal StructuredGraph / LIR | 节点图下降到低层 LIR | 类型区间、guard、profile、FrameState | JIT 内联、去虚化、逃逸分析、反优化与机器码生成 | 活跃 |

**判断：** 语言专属 IR 的核心价值不是“重复造一个 LLVM IR”，而是延迟丢失该语言独有且可优化的语义。所有权、协议见证表、trait、协程和运行时反优化状态都是典型例子。

### 3.3 程序分析与代码转换 IR

| IR / 框架 | 表示 | 主要能力 | 适用判断 | 状态 |
|---|---|---|---|---|
| Soot Jimple | 有类型、无栈三地址码 | JVM/DEX 静态分析、插桩与转换 | Java/Android 分析的成熟基线 | 活跃 |
| Soot Shimple | Jimple 的 SSA 形式 | SSA 数据流分析 | 不是独立通用 IR | 活跃 |
| Soot Baf | 接近 JVM 的栈式表示 | 低层字节码变换与生成 | 旧 Soot 能力，非 SootUp 主打表示 | 维护 |
| Soot Grimp | 聚合后的 Jimple | 反编译与人工阅读 | 不等于可逆源码 AST | 维护 |
| WALA IR | 方法级 SSA 寄存器传送表示 | 调用图、指针分析、切片、数据流 | JVM/Android 与多前端分析框架 | 活跃 |
| LARA/Clava 程序模型 | Joinpoint API + C/C++ AST | 源码查询、切面变换与再生成 | “Virtual AST”不是已核实的独立标准 IR 名称 | 活跃 |
| SUIF1 / SUIF2 | 高层可扩展研究表示 | 循环、并行化、依赖与跨函数分析 | 两代表示不同，适合历史研究 | 历史 |
| COINS HIR/LIR | 高层树形 + 低层机器表示 | 编译器研究、并行化、可重定向生成 | 官方依据不支持固定的 HIR/MIR/LIR 三层命名 | 历史 |

**判断：** 设计模式识别和源码级重构通常需要 AST/HIR 或保留对象模型的程序模型；调用图、指针分析、污点传播更适合 Jimple/WALA 这类显式 CFG/SSA 表示；低层 LLVM IR 适合内存行为和跨语言数据流，但很难可靠恢复源级设计意图。

### 3.4 稳定字节码与可移植执行格式

| 格式 | 执行模型 | 语言与消费方 | 关键语义 | 状态 |
|---|---|---|---|---|
| JVM bytecode | 有类型栈机 + 局部变量槽 | JVM 多语言；验证、解释、JIT | 类、方法、动态分派、异常、注解、运行时元数据 | 活跃标准 |
| .NET CIL/IL | 栈式 CLI + CTS 元数据 | .NET 多语言；JIT/AOT | 类型、泛型、托管引用、异常、调用约定 | 活跃标准 |
| WebAssembly | 低层抽象栈机 + 结构化控制流 | 多语言；Web、WASI、插件与嵌入式运行时 | 函数、表、线性内存；高层对象语义通常不保留 | 活跃标准 |
| Android DEX | 寄存器式指令 + `.dex` 容器 | Android Java/Kotlin；ART | 类、方法、字段、类型、异常、注解 | 活跃格式 |
| ELVM EIR | 六寄存器极简低层 IR | C 前端与大量实验性后端 | 整数、内存、跳转、字符 I/O | 小众活跃 |
| ARK bytecode | `.pa` 文本汇编与 `.abc` 二进制 | OpenHarmony Runtime Core | 指令、类型、函数与运行时文件结构 | 活跃 |

这里需要三个命名澄清：

- WebAssembly 核心规范与宿主无关，不是浏览器专用字节码。
- DEX 是现行格式和指令集载体；Dalvik 是被 ART 取代的旧运行时。
- OpenHarmony Runtime Core 需区分 `.pa` 文本、`.abc` 二进制 ARK bytecode 和编译器内部 CFG/SSA IR；Panda 名称仍存在于历史接口、工具和文件 magic 中，但不宜把所有层次统称为“Panda IR”。

### 3.5 AI、GPU 与异构计算 IR

| IR | 层级与用途 | 生态位置 | 状态 |
|---|---|---|---|
| StableHLO | 基于 MLIR 的稳定算子集合与版本化交换层 | ML 框架与编译器间互操作 | 活跃 |
| XLA HLO | XLA 内部高层优化表示 | 算子与计算图优化，范围大于 StableHLO | 活跃 |
| TVM Relax | 当前图级/模型级 IR | 模型导入、融合、连接低层 tensor primitive | 活跃主线 |
| TVM TensorIR / TIRx / S-TIR | 循环、buffer、调度与硬件映射 | Relax 下层的张量程序优化与生成 | 活跃主线 |
| TVM Relay | 历史函数式图级 IR | TVM 早期模型表示 | 非当前主线 |
| SPIR-V | 标准二进制 shader/compute IR | Vulkan/OpenCL 等环境与厂商驱动之间 | 活跃标准 |
| CUDA Tile IR | 基于 MLIR 的 tile-oriented IR | NVIDIA tiled computation 与 Tensor Core 编译 | 活跃公开项目 |
| Intel vISA | 面向 Intel GPU 的虚拟字节码 IR | 高层编译器与 vISA finalizer 之间 | 活跃厂商 IR |
| HSAIL / BRIG | 并行虚拟指令语言及二进制表示 | HSA Foundation 早期异构计算体系 | 历史 |
| OpenCL SPIR | 基于特定 LLVM bitcode 版本的 OpenCL 映射 | SPIR-V 之前的 OpenCL 中间格式 | 历史 |

**判断：** AI/GPU 编译最能体现多层 IR 的必要性。模型算子、张量循环、tile、线程/内存层级和目标虚拟 ISA 的优化规则不同，单层表示难以同时承载。StableHLO 解决稳定交换，Relax/HLO 解决图级优化，TensorIR/Tile IR 解决调度和硬件映射，SPIR-V/vISA 解决驱动或设备接口。

## 4. IR 的主要目的

### 4.1 编译器优化

SSA、显式 CFG 和 def-use 关系使常量传播、死代码删除、公共子表达式消除、循环优化和跨函数分析更直接。LLVM IR、GIMPLE、SIL、MIR 和 Graal 图均服务于此，但它们保留的语言语义不同。

### 4.2 语言语义检查

越依赖源语言规则，越应在较高层完成。Rust MIR 将 move、borrow 和 drop 显式化，Swift SIL 表达 ownership 与调用约定，适合在下降到通用低层表示前完成安全检查与专属优化。

### 4.3 静态分析与设计模式识别

Jimple 和 WALA IR 将字节码栈行为转为显式局部值、CFG 或 SSA，适合调用图、指针、污点和切片分析。设计模式识别还依赖类层次、声明关系和源位置，宜使用 AST/HIR 或保留对象模型的分析 IR；仅靠 LLVM IR 容易出现语义缺失。

### 4.4 代码转换与多后端生成

Kotlin Backend IR 支撑一门语言到多个平台，MLIR dialect conversion 支撑多个抽象层渐进下降，LARA/Clava 面向源码查询和重写。三者分别代表“单语言多后端”“多领域多层基础设施”和“源码级变换”。

### 4.5 稳定分发与运行时执行

JVM bytecode、CIL、DEX、Wasm 和 ARK bytecode 提供可验证、可序列化的运行时契约。它们的版本兼容、元数据和安全验证能力通常比编译器内部 IR 更重要。

### 4.6 形式化验证

CompCert 为多个 IR 定义操作语义，并证明编译转换保持可观察行为。它展示了多级 IR 除工程解耦外的另一项价值：把大证明拆成可组合的小步语义保持证明。

### 4.7 领域优化与硬件映射

StableHLO、Relax、TensorIR、CUDA Tile IR 和 SPIR-V 将领域知识保留到适合的阶段，使算子融合、布局、循环调度、共享内存、Tensor Core 和设备能力成为一等优化对象。

## 5. 开源托管平台专项检索

### 5.1 检索方法

在 GitHub、GitLab.com、Gitee 和 GitCode 分别组合检索 `intermediate representation`、`compiler IR`、`MLIR`、`static analysis` 及具体项目名，并从项目官网、组织身份、仓库描述、上游链接、协作入口和活动记录核实项目性质。结果分为官方主仓、官方镜像、社区镜像和衍生项目。

### 5.2 平台结果矩阵

| 平台 | 代表性发现 | 主要仓库性质 | 工程判断 |
|---|---|---|---|
| GitHub | llvm/llvm-project、swiftlang/swift、rust-lang/rust、JetBrains/kotlin、oracle/graal、soot-oss/soot、wala/WALA、apache/tvm、openxla/stablehlo | 大量官方主仓与 MLIR 衍生项目主仓 | IR 代码、规范、issue、release 和生态最集中，优先作为一手代码源 |
| GitLab.com | mopsa/mopsa-analyzer、freepascal.org/fpc/source、clash-lang/clash-compiler | 官方主仓与官方 CI 镜像并存 | 有可信主仓，但宽泛搜索中个人导入与镜像较多，需官网反向核验 |
| Gitee | mirrors/llvm-project、mirrors/cppcheck、mirrors/semgrep、openarkcompiler/OpenArkCompiler | 平台镜像为主，另有国内项目官方仓 | namespace 和 PR/issue 能力比 `fork` 字段更能识别镜像；OpenArkCompiler 需单独核实官方身份 |
| GitCode | LLVM、ONNX-MLIR、Torch-MLIR、Semgrep 加速镜像及 OpenHarmony 相关项目入口 | 实时加速镜像和国内生态分发 | 搜索索引可能漏报；页面若声明 GitHub 上游和“仅用于镜像加速”，不能视为主仓 |

### 5.3 代表性平台证据

**GitHub 官方主仓**

- [LLVM/MLIR](https://github.com/llvm/llvm-project)
- [Swift](https://github.com/swiftlang/swift)
- [Rust](https://github.com/rust-lang/rust)
- [Kotlin](https://github.com/JetBrains/kotlin)
- [Graal](https://github.com/oracle/graal)
- [Soot](https://github.com/soot-oss/soot) 与 [WALA](https://github.com/wala/WALA)
- [Apache TVM](https://github.com/apache/tvm)、[OpenXLA StableHLO](https://github.com/openxla/stablehlo)、[NVIDIA CUDA Tile](https://github.com/NVIDIA/cuda-tile)

**GitLab.com 主仓与镜像**

- [MOPSA Analyzer](https://gitlab.com/mopsa/mopsa-analyzer)：项目官网指向的静态分析主仓。
- [Free Pascal Compiler](https://gitlab.com/freepascal.org/fpc/source)：官方开发页给出的源码仓。
- [Clash Compiler](https://gitlab.com/clash-lang/clash-compiler)：仓库声明为 GitHub 主仓的 CI 镜像。

**Gitee 与 GitCode 样本**

- [OpenArkCompiler](https://gitee.com/openarkcompiler/OpenArkCompiler)：国内编译器项目官方仓样本。
- [Gitee LLVM 镜像](https://gitee.com/mirrors/llvm-project)：`Gitee 极速下载/mirrors` 名空间下的平台镜像。
- [GitCode LLVM 镜像](https://gitcode.com/GitHub_Trending/ll/llvm-project)、[ONNX-MLIR 镜像](https://gitcode.com/gh_mirrors/on/onnx-mlir)、[Torch-MLIR 镜像](https://gitcode.com/gh_mirrors/to/torch-mlir)：页面指向 GitHub 上游的加速镜像。

### 5.4 平台检索结论

1. 仓库身份必须由官方站点反向链接、组织 owner、上游声明和协作入口共同确认，不能只看仓库名或 `fork` 字段。
2. 镜像适合下载与网络加速，不适合用来判断治理、issue 响应、release 可信度和社区规模。
3. GitHub 聚集了最多活跃 IR 主仓和衍生生态；GitLab 在研究编译器与静态分析领域仍有独立价值。
4. Gitee/GitCode 对国内访问和本地项目发现有价值，但关键词搜索存在动态页面、索引漏报和镜像占比高等限制，应配合定点仓库核验。

## 6. 选型建议

| 目标 | 首选参考 | 原因 | 注意事项 |
|---|---|---|---|
| 通用多语言后端 | LLVM IR | 后端、优化、工具与生态成熟 | 高层语义需在前置 IR 处理 |
| 多层级、可扩展编译基础设施 | MLIR | 方言、Operation/Region、conversion 和 pass 机制完整 | 需要治理方言边界与 lowering 契约 |
| 单语言语义检查与专属优化 | SIL / MIR / Kotlin IR 模式 | 保留所有权、泛型、对象与平台语义 | 不应过早下降到通用 IR |
| JVM/Android 静态分析 | SootUp/Jimple、WALA | 字节码到显式三地址或 SSA，分析生态成熟 | Android、插桩和新旧框架能力需逐项确认 |
| 源码模式识别与重构 | AST/HIR、Clava 类程序模型 | 保留声明、类层次、源位置与可再生成信息 | 低层 IR 只能作为行为证据补充 |
| 可移植运行时格式 | JVM bytecode、CIL、Wasm、DEX、ARK bytecode | 稳定序列化、验证与运行时生态 | 兼容策略和宿主接口是核心设计 |
| AI 模型交换 | StableHLO | 明确的版本兼容与算子契约 | XLA HLO 更适合作为内部优化表示 |
| AI/GPU 分层优化 | Relax + TensorIR、MLIR 方言体系 | 图、循环、tile 与目标层职责清晰 | 避免用单层 IR 同时承载全部抽象 |
| 高可信编译研究 | CompCert IR 体系 | 操作语义与转换正确性证明 | 语言和目标覆盖比通用工业编译器窄 |

若要自建 IR，建议先回答五个问题：

1. 哪些源语言或领域语义必须保留到哪一层？
2. 核心消费者是分析器、优化器、运行时、硬件后端还是外部工具？
3. IR 是内部实现细节，还是需要长期兼容的交换格式？
4. 合法性由 verifier、类型系统、测试还是形式化语义保障？
5. 扩展单位是新指令、方言、pass、插件，还是独立的上下层 IR？

## 7. 初步清单核验结论

| 初步条目 | 核验结论 |
|---|---|
| LLVM IR 是低层 SSA IR | 基本成立；需补充它仍是类型化、目标无关表示，不等同机器 IR |
| MLIR 是多层级 IR | 成立；更准确地说是承载多种方言与层级的 IR 基础设施 |
| Dalvik Bytecode | 建议写 DEX bytecode；DEX 活跃，Dalvik runtime 已退出主线 |
| Kotlin IR | 需区分 K2 FIR 与 Backend IR |
| Shimple / Grimp | 分别是 Jimple 的 SSA 形式与聚合表示，不宜当作独立通用体系 |
| LARA Virtual AST | 未核实为官方独立 IR 名称，应表述为 LARA joinpoint 暴露的程序模型 |
| COINS HIR/MIR/LIR | 一手资料支持 HIR/LIR；MIR 不宜列为固定核心层 |
| HLO / XLA IR | 需区分稳定交换层 StableHLO 与 XLA 内部 HLO |
| Relay / TensorIR | Relay 非当前图级主线；当前应重点关注 Relax 与 TensorIR/TIRx/S-TIR |
| OpenCL IR | 需区分历史 SPIR、活跃 SPIR-V 与 SPIRV-LLVM-Translator |
| MAPLE IR / Panda IR | Maple 属 OpenArkCompiler 体系；OpenHarmony 需区分 ARK bytecode 与 Runtime Core 内部 SSA IR |
| Tree / DAG / TAC / SSA / 后缀表示 | 属结构或性质，不是单一项目 IR |

## 8. 局限

- “支持语言”可能指可生成该 IR 的前端、可运行该字节码的语言、共享同一优化器的入口或领域输入，报告已按项目语境解释，不把数量直接横向比较。
- 项目活跃度是时间敏感信息。本报告优先引用维护主体、规范、release 和主仓状态，不用单次提交时间给出长期保证。
- 部分历史项目的官方资料停留在旧站点或归档仓，适合研究设计谱系，不适合作为新项目默认依赖。
- 开源平台搜索结果受登录、动态渲染、索引延迟和镜像策略影响，平台矩阵用于识别生态分布，不用于精确统计项目数量。

## 9. 主要参考资料

### 通用与语言 IR

1. LLVM, [LLVM Language Reference Manual](https://llvm.org/docs/LangRef.html)
2. MLIR, [Language Reference](https://mlir.llvm.org/docs/LangRef/) 与 [Rationale](https://mlir.llvm.org/docs/Rationale/Rationale/)
3. GCC, [GENERIC](https://gcc.gnu.org/onlinedocs/gccint/GENERIC.html)、[GIMPLE](https://gcc.gnu.org/onlinedocs/gccint/GIMPLE.html)、[RTL](https://gcc.gnu.org/onlinedocs/gccint/RTL.html)
4. Swift, [Swift Intermediate Language](https://github.com/swiftlang/swift/blob/main/docs/SIL/SIL.md)
5. Rust Compiler Development Guide, [HIR](https://rustc-dev-guide.rust-lang.org/hir.html) 与 [MIR](https://rustc-dev-guide.rust-lang.org/mir/index.html)
6. Kotlin, [IR Overview](https://github.com/JetBrains/kotlin/blob/master/compiler/ir/ReadMe.md)
7. CompCert, [Documentation](https://compcert.org/doc/) 与 [Release](https://compcert.org/release/)

### 分析、字节码与运行时

8. Oracle, [Java Virtual Machine Specification SE 26](https://docs.oracle.com/javase/specs/jvms/se26/html/)
9. ECMA, [ECMA-335 Common Language Infrastructure](https://ecma-international.org/publications-and-standards/standards/ecma-335/)
10. WebAssembly, [Core Specification](https://github.com/WebAssembly/spec) 与 [WASI](https://wasi.dev/)
11. Android, [ART](https://source.android.com/docs/core/runtime)、[DEX Format](https://source.android.com/docs/core/runtime/dex-format)
12. Soot, [Official Repository](https://github.com/soot-oss/soot) 与 [SootUp Documentation](https://soot-oss.github.io/SootUp/latest/)
13. WALA, [IR API](https://wala.github.io/javadoc/com/ibm/wala/ssa/IR.html)
14. OpenHarmony, [ArkCompiler Runtime Core](https://github.com/openharmony/arkcompiler_runtime_core)

### AI、GPU 与领域 IR

15. OpenXLA, [StableHLO Specification](https://github.com/openxla/stablehlo/blob/main/docs/spec.md) 与 [Compatibility](https://github.com/openxla/stablehlo/blob/main/docs/compatibility.md)
16. Apache TVM, [Architecture](https://tvm.apache.org/docs/arch/index.html)、[Relax](https://tvm.apache.org/docs/deep_dive/relax/index.html)、[TensorIR](https://tvm.apache.org/docs/deep_dive/tensor_ir/index.html)
17. Khronos, [SPIR-V Registry](https://registry.khronos.org/SPIR-V/) 与 [SPIRV-Tools](https://github.com/KhronosGroup/SPIRV-Tools)
18. NVIDIA, [CUDA Tile](https://github.com/NVIDIA/cuda-tile)
19. Intel, [GEN Virtual ISA Specification](https://github.com/intel/intel-graphics-compiler/tree/master/documentation/visa)
20. OpenArkCompiler, [Maple IR Design](https://github.com/openmaple/MapleCompiler/blob/master/doc/en/MapleIRDesign.md)

### 托管平台专项检索入口

21. GitHub, [MLIR repositories](https://github.com/search?q=MLIR&type=repositories)
22. GitLab, [MLIR projects API](https://gitlab.com/api/v4/projects?search=MLIR)
23. Gitee, [MLIR repository search](https://so.gitee.com/?q=MLIR&type=repository)
24. GitCode, [MLIR repository search](https://gitcode.com/search?keyword=MLIR)