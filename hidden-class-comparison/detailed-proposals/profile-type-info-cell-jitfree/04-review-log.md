# 审视日志（ProfileTypeInfoCell 编译期裁槽）

本文档保存当前两阶段裁槽方案的有效审视意见和闭环结论。审视对象：`01-背景.md`、`02-需求.md`、`03-方案设计.md`。

## 第 1 轮：项目管理者（PM）

**审视意见**

1. 阶段一收益是否依赖未验证的 cell 消除比例？
2. `CELL_1/N` 是否纳入收益？
3. 两阶段的工作量能否独立核算？

**闭环结论**

- 两阶段只缩小现存 cell，不减少对象数量，收益固定为 `8N/16N`；
- 快手前后台按 `CELL_0 + CELL_1 + CELL_N` 全量计数；历史 Top13 仅有 `CELL_0` 数据，明确标为收益下界；
- 当前两阶段合计 55 人日，其中阶段一 24 B 可独立交付，阶段二等待 PGO-free 产品决策。

## 第 2 轮：SE / 架构师

**审视意见**

1. 16/24/32 B 多档布局如何避免内部 ABI 混用？
2. AOT-free 是否足以删除 `Handle`？
3. 汇编解释器读取 `Value` 是否受影响？

**闭环结论**

- `ARK_PROFILE_CELL_HAS_MACHINE_CODE` 和 `ARK_PROFILE_CELL_HAS_HANDLE` 纳入构建 feature fingerprint；同一镜像只允许一种编译期尺寸，持久产物跨档双向稳定拒绝；
- 不足。PGO 可在无 AOT 时独立初始化、采集并保存 `.ap`，阶段二必须以显式 PGO-free 能力闭包为前置；
- `Value` 始终位于 offset 8，解释器和 IC 热路径不增加档位分支，x64/AArch64 路径纳入回归。

## 第 3 轮：测试工程师

**审视意见**

1. 24/16 B 对象边界如何验证？
2. PGO 的 `Handle` 读写是否完整覆盖？
3. shallow bytes 如何映射到设备内存？

**闭环结论**

- 各目标尺寸后布置哨兵对象，覆盖 young/old/full/CMC/compaction 压力测试；同时核验 allocator 实际字节和 Region used；
- 构建矩阵包含 JIT-free+PGO 的 24 B 档，并专门验证无 AOT情况下的 define-class 采集、dump 和 `.ap` merge；
- snapshot `self_size` 只作为对象浅层收益，不设到 Region committed、RSS、PSS 或峰值的固定折算，正式结果采用 clean A/B。

## 第 4 轮：VM 开发者

**审视意见**

1. `UpdateProfileTypeInfoCellType` 更换 `CELL_0/1/N` HClass 时，尺寸是否一致？
2. local/shared Empty cell 和 GC visitor 是否覆盖？
3. 残留专用字段消费者如何暴露？

**闭环结论**

- 三类 HClass 在同一构建统一使用当前 `SIZE`，状态转级只换 HClass，不改变实例尺寸；
- local/shared factory、Empty cell、xray visitor、weak processor、serializer 和 snapshot 全部纳入目标档位矩阵；
- 目标档位不提供空 accessor：删除字段后对应 offset/accessor 不声明，残留引用必须构建失败，并辅以全仓静态扫描。

## 第 5 轮：发布 / 兼容性负责人

**审视意见**

1. 多构建档位是否造成运行时双路径？
2. 24/16 B runtime 误加载 32 B snapshot 或 AOT/AI 产物如何处理？
3. OTA 是否允许只更新 runtime？

**闭环结论**

- 条件编译集中于布局常量、accessor 和能力专用消费者，运行时不按开关切换对象尺寸；
- feature fingerprint 和版本校验覆盖 snapshot、AOT/AI、AppSpawn 和 rawheap，跨档双向稳定拒绝；
- 禁止只更新 runtime 而保留旧持久产物。

## 第 6 轮：源码复核

1. **`MachineCode` 消费者**：JIT 安装（`jit/jit_task.cpp:388`）、deopt 清理（`deoptimizer/deoptimizer.cpp:684`）、诊断（`stubs/runtime_stubs.cpp:4878`），均纳入 JIT 能力闭包。
2. **`Handle` 消费者**：profiler stub 直接写入（`compiler/profiler_stub_builder.cpp:155-160`）、`PGOProfiler` 直接读取（`pgo_profiler/pgo_profiler.cpp:1338-1393`）、local/shared factory 初始化；不是 AOT-only 字段。
3. **PGO/AOT 关系**：AOT 可消费 PGO 产物，但 PGO 采集和保存不依赖 AOT；已有 AOT 产物时当前实现反而可能关闭 PGO profiler。因此“关闭 AOT即可删除 Handle”不成立。
4. **allocator**：tagged 对象按 8 B 对齐并采用 bump 分配，24/16 B 具备兑现基础；仍保留 Region 实测门槛。
5. **JSFunction 边界**：本方案只修改 cell，自有 `JSFunction::MachineCode` 和冻结的 112 B JSFunction 布局不变。

## 第 7 轮：快手前后台 full-GC 快照复核

前台与后台 rawheap 使用同一 API 26 `rawheap_translator` 2.0.0 转换；后台为应用进入后台并执行 full GC 后的独立存活堆。冻结数据见 `../../evidence/kuaishou-background-paired-census.json`。

| 指标 | 前台 Kuaishou | 后台 full-GC Kuaishou | 后台相对前台 |
|---|---:|---:|---:|
| 存活 cell 数 `N` | 67,940 | 57,714 | -10,226 |
| `CELL_0 / CELL_1 / CELL_N` | 67,402 / 73 / 465 | 57,186 / 25 / 503 | -10,216 / -48 / +38 |
| cell 浅层堆 | 2,174,080 B（2.073 MiB） | 1,846,848 B（1.761 MiB） | -327,232 B |
| 阶段一 24 B 总收益 `8N` | 543,520 B（0.518 MiB） | 461,712 B（0.440 MiB） | -81,808 B |
| 阶段二 16 B 累计收益 `16N` | 1,087,040 B（1.037 MiB） | 923,424 B（0.881 MiB） | -163,616 B |

`CELL_0/1/N` 只表示同 slot 的复用级别，不影响裁槽计算；三个类型的现存对象均按相同的 `8N/16N` 口径计入。Region 碎片、GC 扫描和 RSS/PSS 留待实现后 A/B。

## 审视结论汇总

当前方案只保留两个编译期裁槽阶段：阶段一删除 JIT-only `MachineCode`（32→24 B），阶段二在显式 PGO-free 构建中再删除 `Handle`（24→16 B）。字段消费者、能力闭包、布局、兼容、GC/工具、收益和 55 人日工作量已形成闭环；阶段二唯一产品前置是冻结 PGO-free 构建。
