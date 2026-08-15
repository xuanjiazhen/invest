# 审视日志（ProfileTypeInfoCell JIT-free 裁剪）

本文档独立保存 5 轮不同角色审视记录与闭环意见，不混入正式方案文档。审视对象：01-背景 / 02-需求 / 03-方案设计。

## 第 1 轮：项目管理者（PM）

**审视意见**
1. 7.13 MiB 浅层收益 vs 48 人日，且强依赖编译期分档能力落地——若分档能力延期，本方案是否有独立价值？
2. cell_1/cell_n 数量未统计，收益是否偏保守？

**闭环结论**
- 澄清：本方案是「编译期 JIT-free 变体」的组成项，分档能力是前置载体；若分档延期则方案同步后移，但设计不依赖分档具体实现，可先行冻结能力闭包定义。
- 采纳：cell_1/cell_n 数量在新一轮基线快照后补充，当前收益按 cell_0 下界表述（需求 §2 已注明）。

## 第 2 轮：SE / 架构师

**审视意见**
1. 24 B/32 B 双布局的 feature fingerprint 与既有 AOT/snapshot 版本机制如何共存？
2. 汇编解释器（x64/AArch64）读取 cell.Value 的路径是否受布局影响？

**闭环结论**
- 澄清：`ARK_PROFILE_CELL_HAS_MACHINE_CODE` 独立纳入构建 fingerprint，与 AOT 版本并列校验；双布局是编译期确定的，同一镜像无混堆。
- 采纳：asm interpreter `Value` 读取路径（`asm_interpreter_call.cpp`）纳入回归，AArch64 补充用例。

## 第 3 轮：测试工程师

**审视意见**
1. 24 B 对象边界是否用哨兵对象压力验证？
2. PGO dump/merge 的 Handle 读写路径覆盖？

**闭环结论**
- 采纳：DT 用例含「24 B cell 后放哨兵对象 + 压力 GC」；构建矩阵含 JIT-free+PGO（Handle 读写、dump/merge 回归）。

## 第 4 轮：VM 开发者

**审视意见**
1. `UpdateProfileTypeInfoCellType` 换 HClass 时，CELL_0/1/N 的尺寸依赖是否一致？
2. Empty cell（read-only/shared heap）的 24 B 分配与 visitor 是否覆盖？

**闭环结论**
- 澄清：三类 HClass 在同一构建统一使用当前 `SIZE`，换 HClass 只改状态不改尺寸（方案设计 §4.2）；
- 采纳：read-only/shared Empty cell 的 24 B 分配路径与 visitor 验证纳入 GC 矩阵。

## 第 5 轮：发布 / 兼容性负责人

**审视意见**
1. JIT-free 与 JIT-enabled 双镜像是否造成维护双份代码路径的成本？
2. 24 B runtime 误加载 32 B snapshot 的兜底？

**闭环结论**
- 澄清：条件编译集中在头文件常量与少数接口（accessor/安装/诊断），双路径编译期确定、非运行期分支，维护成本可控；
- 采纳：版本 feature fingerprint 双向稳定拒绝作为硬门槛，禁止 OTA 只更 runtime。

## 第 6 轮：独立复核（源码重验证 + 分档需求对齐）

**审视意见与核验结果**（本轮为对既有 01/02/03 的独立源码复核，基线 `ets_runtime`，全部结论附源码位置）：

1. **Handle 槽消费者核验**：仓库级运行时消费者仅 PGO 链路——profiler stub 写入（`compiler/profiler_stub_builder.cpp:155`，写 weak 构造函数引用）、PGOProfiler 读取（`pgo_profiler/pgo_profiler.cpp:1338`）、factory 初始化（`object_factory.cpp:5560`、`shared_object_factory.cpp:597`）。IC/AOT/解释器不读写该槽。**原方案把 Handle 视为不可裁剪是保守了**：≤6G 分档若 PGO 随 AOT 一并关闭，cell 可到 16 B，cell_0 收益从 7.13 MiB 提升到 14.27 MiB。
2. **MachineCode 槽消费者核验**：安装（`jit/jit_task.cpp:388`）、deopt 清理（`deoptimizer/deoptimizer.cpp:684`）、诊断（`stubs/runtime_stubs.cpp:4878`）三类，全部在 JIT 能力闭包内，无 interpreter-only 消费者。原方案结论成立。
3. **与产品分档对齐**：≤6G 手机宏编译关闭 AOT+JIT 为既定需求，本方案是该分档的直接受益项；24 B 档无新增依赖，16 B 档新增「AOT 关闭 ⇒ PGO 关闭」的产品决策依赖。
4. **allocator 取整风险降级**：ArkVM tagged 对象经 `DEFINE_ALIGN_SIZE` 按 8 B 对齐、young/old 空间 bump 分配，无 32 B size class 取整机制；原「高」级风险降为「中」，但保留 Region 实测核验门槛。
5. **shared Empty cell**：`shared_object_factory.cpp:593-597` 创建 shared Empty cell 并初始化 Handle——16 B 档的 shared 路径需同步裁剪（已补入涉及模块与 DT 矩阵）。

**闭环结论**：01/02/03 已按本轮意见更新（三档布局、双层闭包、工作量 48→53 人日、风险表与 DT 矩阵）；16 B 档以产品冻结「AOT 关闭 ⇒ PGO 关闭」为放行前置，未冻结前构建矩阵不包含 16 B 档。

## 第 8 轮：人工审视 TODO（2026-08-15，方案合并）

**人工意见**：将 feasible-proposals/15（ProfileTypeInfoCell 惰性分配）合并至本方案，并细化完善。

**闭环结论**：已合并为两阶段方案并全文细化——01-背景新增 §4「cell 的分配时机」（7 处 DEFINEFUNC 分配点、Empty→cell 既有机制、V8 先例、99.9% cell_0 事实）；02-需求改为两阶段目标、组合收益模型 `N×(32e+tier(1−e))`、工作量合并重估 84 人日（阶段一可独立交付约 30 人日）、风险与验收补阶段一条目、插桩消除率 e 为阶段一立项门槛；03-方案设计新增 §4.1 阶段一设计（分配点删除表、首触发路径、PGO 条件保留、共享计数等价、否决阈值触发的 ADR 理由）、利弊表与 DT 矩阵补阶段一用例；竞品对照补 V8 lazy feedback vectors。原 feasible/15 目录移除。

## 审视结论汇总

前 5 轮共 8 项意见全部闭环；第 6 轮独立复核新增 5 项（Handle 可裁剪、消费者清单固化、分档对齐、风险降级、shared 路径补充），已同步落稿。无遗留问题。