# 可行方案索引（置信度 ≥ 60%）

本目录收录**置信度 ≥ 60% 的可行内存优化方案**。其中 ≥80% 的为高置信方案，60%–80% 的为方向成立、收益待实测的中等置信方案。低于 60% 的方案统一归档到 `../pending-review/`。

## 1. 分类标准

一个方案进入本目录必须同时满足：

1. **事实基础可核验**：对象布局/字段/创建路径有 `ets_runtime` 源码直接佐证，或坏味道对象分布有快照节点数据直接佐证，且不存在被复核意见推翻的推导；
2. **收益口径正确**：收益数字为快照可复算的**确值**或明确标注的**上界**，不使用「无可见对象边 = Hole」这类被否定的换算；
3. **机制成立**：源码内已有对应机制（或成熟先例），实现路径明确；
4. **无致命缺陷**：不存在复核意见（`HERMES REVIEW APPENDIX 2026-08-12`）指出的 P0 级错误。

「置信度」为三项的加权：事实置信度（源码 + 快照）、机制置信度（实现可行性）、收益置信度（数字可信度）。凡收益为「上界、需实测」的方案，其收益置信度单独标注，不并入综合置信度。

## 2. 事实基线（已源码核验，所有方案的地基）

| 对象 | 尺寸 | 关键字段 | 源码位置 |
|---|---|---|---|
| `JSHClass` | 88 B | 8 个 Tagged 字段：Proto/Layout/Transitions/Parent/ProtoChangeMarker/ProtoChangeDetails/EnumCache/DependentInfos + 3 个 BitField | `js_hclass.h:2215-2226` |
| `LayoutInfo`（去重后 735,734 个） | **109.25 MiB**（JSHClass 本体的 1.59 倍） | 每属性 Key 8 B + Attr 8 B 交织（Attr 实为 uint32 位域） | `layout_info.h:30`；`evidence/top13-layout-dedup-census.json` |
| `Method` | 64 B | ConstantPool/CallField/NativePointerOrBytecodeArray/CodeEntryOrLiteral/LiteralInfo/ExtraLiteralInfo/ExpectedPropertyCount；**不含** machine_code/baseline_code | `method.h:485-499` |
| `FunctionTemplate` | 40 B | 仅 Method/Module/RawProfileTypeInfo/Length | `js_function.h:732-758` |
| `AccessorData` | 24 B | Getter/Setter 两个 Tagged 槽 | `accessor_data.h:83-88` |
| `ProfileTypeInfoCell` | 32 B | Value/MachineCode/Handle；**MachineCode 消费者全在 JIT 闭包（安装/deopt/诊断），Handle 消费者全在 PGO 链路（profiler stub/PGOProfiler）** | `ic/profile_type_info_cell.h:34-38` |
| `SourceTextModule` | 存在 | 继承 ModuleRecord | `module/js_module_source_text.h:67` |

对象人口（`team_interop/analysis/top13-jit-off/top13-jit-off-estimates.csv`，13 应用合计）：

| 对象 | 数量 | 备注 |
|---|---|---|
| `jshclass` | 819,497 | self_size 统一 88 B |
| `jsfunction` 完整尾部 | 2,830,994 | 其中 NAPI 创建 790,312、普通 2,040,682 |
| `enum_cache`（非空） | 6,189 | 占 jshclass 0.755% |
| `proto_change_marker`（非空） | 15,631 | 占 1.907% |
| `proto_change_details`（非空） | 12,868 | 占 1.570% |
| string 节点 | 83.03 MiB | ≤24 B 桶 20.28 MiB、>1K 桶 32.63 MiB、无 sliced/concat 节点；ConstantPool 持有（去重）15.38 MiB（`evidence/top13-string-array-census.json`、`evidence/top13-layout-dedup-census.json`） |

## 3. 被推翻的结论（防止后续被误导）

以下结论出现在既有文档中，但经源码核验或复核意见判定**不成立**，任何后续分析不得沿用：

| 被推翻结论 | 出处 | 正确事实 |
|---|---|---|
| ConstantPool 稀疏化可省 250–280 MiB | `top13-heap-optimization-opportunities.md:36` | 「无可见对象边」是 Hole 的上界，不是 Hole；连续数组容量取决于最高访问 index 而非填充率（ConstantPool 稀疏化复核已否决） |
| Method 瘦身可裁剪 machine_code/baseline_code 字段 | 同上 `:108` | `Method` 无这两个字段（`method.h:485-499`） |
| FunctionTemplate 40 B 含 JIT/调试字段可裁剪 | 同上 `:172` | `FunctionTemplate` 仅 Method/Module/RawProfileTypeInfo/Length（`js_function.h:732-758`） |
| ProfileTypeInfoCell 在 JIT-off 下无用途可整体裁剪 | 同上 `:190-195` | cell_0 由解释器 IC 反馈路径分配（`interpreter-inl.cpp:1046-1063`），非 JIT 专属 |
| 「无 JIT 即可外迁 ProtoChange/EnumCache/DependentInfos」 | 已清理的 JIT 分档布局提案两篇 | ProtoChange/EnumCache 服务原型变更与枚举语义，关闭 JIT 仍会被使用（`jshclass-layout-review.md` 复核） |
| JSHClass 88B 是「多写了 32B 的对象内属性槽」 | 已清理的早期对比报告 | 对象内属性槽不在 JSHClass 自身 88 B 内（`CONTEXT.md:69-71`） |
| 520–620 MiB 堆内合计 | `top13-heap-optimization-opportunities.md:353` | 多项方案覆盖同一对象链，重复计数，不得发布 |
| `JSApiFunction` 瘦身可让 88 B `JSHClass` 缩小 8 B | 已清理的 JSApiFunction 双宏分析 | `OPTIMIZED_FUNCTION_CAPACITY_OF_IN_OBJECTS=3` 减少的是函数**实例**的 8 B 槽，不是 JSHClass 自身 |

## 4. 本目录方案清单

| 编号 | 方案 | 侧 | 收益口径 | 综合置信度 |
|---|---|---|---|---|
| 02 | [应用侧内存优化统一清单](./02-app-side-consolidated/) | 应用 | A1–A6 六项（详见清单，部分为上界） | 70–82%（逐项标注） |
| 04 | [字符串优化](./04-string-optimization/) | VM | 短串 dedup 预估 6–15 MiB（真实口径 126 MiB，dupRatio 待插桩） | 75% |
| 11 | [FunctionTemplate 按需创建](./11-functiontemplate-on-demand/) | VM | 上界 36.39 MiB，按 neverInstantiated% 折算（插桩 patch 已备） | 65% |
| 14→detailed | [LayoutInfo 属性描述槽压缩](../detailed-proposals/layoutinfo-attr-packing/) | VM | A 档 6B 无损 10.42 MiB；B 档 4B（需迁移 13 运行时位）23.17 MiB | 70% |
| 15 | [ProfileTypeInfoCell 按需分配](./15-profile-cell-lazy-allocation/) | VM | `32eN-M`，消除率与延迟绑定成本待插桩 | 65% |

> 方案 05/06/14 已升级为详细方案：05/06 见 `../detailed-proposals/jshclass-auxdata-sidecar/`、`../detailed-proposals/native-interop-lazy-binding/`；14 见 `../detailed-proposals/layoutinfo-attr-packing/`。方案 15 保留为待验证候选，与 `../detailed-proposals/profile-type-info-cell-jitfree/` 的编译期裁槽独立。
> 原 01（JSHClass 零实例回收）机制已实现，无增量收益。
> 人工审视否决（见 `../pending-review/rejected.md`）：07 JSFunction 代码槽移除（**JSFunction 布局冻结为硬约束**）、08 AccessorData 内联、09 TaggedArray trim、10 模块元数据压缩、12 ClassLiteral 惰性驻留、13 method_idx 缩减；02/03 的应用侧内容合并入 02 统一清单，框架侧改动不做。

> 说明：在纯静态证据（源码 + 快照）范围内，没有任何方案能达到「净收益已通过 clean A/B 实测验证」的置信度；上面各项是**机制成立 + 事实确凿 + 收益口径正确**、可作为明确下一步验证目标的方案。其余见 `../pending-review/`（含竞品措施迁移排查 `competitor-memory-sweep.md`）。
