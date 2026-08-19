# 审视日志（JSHClass AuxData Sidecar）

本文档独立保存 5 轮不同角色审视记录与闭环意见，不混入正式方案文档。审视对象：01-背景 / 02-需求 / 03-方案设计。

## 第 1 轮：项目管理者（PM）

**审视意见**
1. 收益 17.724 MiB（浅层模型）相对 80 人日投入的 ROI 是否合理？是否有更小投入的先导验证？
2. 排期 7–9 周是否可压缩？关键路径是什么？

**闭环结论**
- 采纳：ROI 合理——17.7 MiB 相对 JSHClass 浅层堆（68.8 MiB）降 26.0%，且为确定性浅层收益（非上界推导）；先导项可拆 AR1（64 B 布局 + AuxData helper + factory），约 12 人日先行验证布局与分配发布。
- 关键路径为 compiled 全路径改造（20 人日）与语义迁移（18 人日），并行资源充足时可压缩至 7 周。
- 处理：需求文档 §3 排期表不变，补充 AR1 先导拆分建议。

## 第 2 轮：SE / 架构师

**审视意见**
1. 主对象仍保留 8 B AuxData 槽——为什么不用「主对象无槽 + 全局弱表」以进一步省 6.25 MiB？
2. GC 扫描槽减少 36% 是静态模型，sidecar 分散访问的 cache 局部性与对象头增加的影响未量化。

**闭环结论**
- 澄清：弱表路径被否决——22,569 项弱表本体约 2.0 MiB，且需 ephemeron fixpoint、死键清理、shared heap 特殊处理；保留 8 B 槽换来确定性强引用生命周期，代价是放弃约 4.2 MiB 潜在净收益，属于明确权衡（已在方案设计 §4.6 记录）。
- 采纳：GC 收益以实测为准（方案设计 §2.6、需求 §4 已写明静态模型不承诺）。

## 第 3 轮：测试工程师

**审视意见**
1. 并发首次写不同槽的竞态窗口是否有 TSAN 覆盖？
2. old HClass 指向 young 载荷的 remembered set 是否在用例矩阵？

**闭环结论**
- 采纳：DT 用例含「并发首次写不同槽」（两值最终都存在）与「old→young 载荷」；验证矩阵补充 TSAN + 强制 young/full GC 压力。

## 第 4 轮：VM 开发者

**审视意见**
1. `EnsureAuxDataAndSet` 若在 `DISALLOW_GARBAGE_COLLECTION` 区间被首次调用如何处理？
2. compiled 路径改造后，旧 offset 的仓库级引用归零如何静态保证？

**闭环结论**
- 澄清：方案设计 §4.3 已规定——不允许在 no-GC 区间首次分配，调用点须提前确保 sidecar 或转 runtime slow path；实现时冻结全部调用点清单。
- 采纳：仓库级静态扫描（`PROTO_CHANGE_MARKER_OFFSET` 等引用数=0）作为硬门槛，纳入 CI。

## 第 5 轮：发布 / 兼容性负责人

**审视意见**
1. JSHClass offset 变化对系统镜像中预编译产物（snapshot/AOT/stub）的耦合？
2. OTA 升级时旧 AOT 被拒绝的用户体验影响？

**闭环结论**
- 澄清：JSHClass 无用户侧指针复制兼容约束（人工评审已确认），内部编译契约通过 `.an/.ai` 版本 bump + strict match 闭合；旧产物拒绝是安全行为，OTA 必须捆绑新 AOT 产物。
- 处理：需求 §4 风险表已覆盖「新旧版本稳定拒绝」。

## 第 6 轮：独立复核（源码重验证）

**核验结果**（对 01/02/03 的关键事实逐条对源码复核，基线 `ets_runtime`）：

1. 布局 88 B、四槽偏移 48/56/64/72、`TaggedArray(4)=48 B`（`DATA_OFFSET=16 + 4×8`）、shared factory 按 `JSHClass::SIZE` 分配——全部与源码一致，无出入。
2. **Clone 行为等价性确认**：`JSHClass::Copy`（`js_hclass-inl.h:285-292`）只复制 Proto/BitField/IsAllTaggedProp/NumberOfProps/BitField2（带掩码），**不复制**四个稀疏字段——设计文档「Clone 后 AuxData=Null」与现状语义等价，该断言成立。
3. `RefreshUsers` 只迁移 `ProtoChangeDetails` 并清空 old——与 `js_hclass.cpp:1309-1325` 一致。
4. **旧 offset 消费者全量冻结**：仓库级共 7 个文件（circuit_builder / stub_builder-inl / hcr_circuit_builder.h:220 / new_object_stub_builder / base_serializer:180-188 / js_metadata_test / enum_cache.h 后两者为 `EnumCache` 自身字段非 JSHClass 槽）；静态归零扫描须按 `JSHClass::` 限定，避免 `EnumCache::ENUM_CACHE_OFFSET` 误报——已补入 §4.5。
5. **设计缺口补齐**：原设计一步切 64 B，compiled offset 契约要求全量 clean rebuild，无法渐进验证——补充分阶段上库策略（§4.7：S1 加槽双写 96 B → S2 删槽 64 B → S3 工具链收尾），并把「创建即分配」四入口的 no-GC 审计清单固化为 §4.6。
6. **打桩复测建议**：Top13 基线为 JIT-off 快照，`DependentInfos` 非默认仅 5 个的观测不覆盖 JIT-enabled 场景（lazy-deopt 依赖安装在 JIT-on 下会写该槽）。验收门槛已补充：JIT/AOT-enabled 构建复测四字段联合分布，覆盖率须远离 50% break-even；若覆盖率显著上升，GC 扫描收益模型须按新分布复算。

**闭环结论**：01/02/03 已按本轮更新（§4.5 扫描作用域、§4.6 创建入口审计、§4.7 分阶段上库；需求 §4 新增 no-GC 与 JIT-on 复测两项风险；§5 增补 JIT-enabled 复测门槛）。无遗留问题。

## 第 7 轮：人工审视 TODO 闭环（弱表评估 + 布局对比）

**人工意见**（原文摘录）：
1. 「如果不采用强引用而是采用弱表，是否能复用已有的弱表 Map 具体实现？如果采用弱表会产生多少额外工作量？哪些模块受到影响？」
2. 「此处需要给出当前已有布局，提供修改前、修改后完整布局对比。」

**闭环结论**：
1. 新增 §4.9 弱表路线评估：可复用底座为 `JSWeakMap`/`EphemeronHashTable`（`js_weak_container.h:22`，需去 JSObject 包装）与 `TransitionsDictionary` 的弱值先例；增量工作量 +22–30 人日；影响 GC（ephemeron/死键）、runtime（根与表锁）、compiler（fast path 退化为 runtime call）、DFX；内存净增益上限 ≈ +4.6 MiB（省 6.25 MiB 主槽 − 多 ~1.6 MiB 表成本）。维持强 sidecar 首选，弱表降级为二期探索项。
2. §4.1 重写为修改前后逐偏移对比表（88 B → 64 B，四稀疏槽 → AuxData[n]，BitField2 前移）。

## 第 8 轮：人工审视 TODO 闭环（字段示例代码）

**人工意见**：以示例代码的形式展开解释这几个字段的具体用途。

**闭环结论**：01-背景 §3 展开为 §3.1–3.4，每个字段给出「触发代码 → VM 内部动作（源码位置）→ 用户可感知效果」三段式：EnumCache（for-in 重复枚举）、ProtoChangeMarker（原型修改后 IC 立即见新值）、ProtoChangeDetails（setPrototypeOf 后监听迁移）、DependentInfos（常量字段假设失效触发 lazy-deopt）。

## 审视结论汇总

前 5 轮 8 项意见全部闭环；第 6 轮独立复核 6 项（事实全对、Clone 等价确认、消费者清单冻结、扫描作用域修正、分阶段策略、JIT-on 复测门槛），已同步落稿。无遗留问题。

## 第 9 轮：Kuaishou 后台 full-GC 快照复核

**评估口径**：前台和后台 rawheap 均由同一 API 26 `rawheap_translator` 2.0.0 转换；本轮只比较 Kuaishou 单应用，不与 Top13 汇总混算。后台样本为应用进入后台并执行全量 GC 后的存活堆。冻结数据见 `evidence/kuaishou-background-paired-census.json`。

| 指标 | 前台 Kuaishou | 后台 full-GC Kuaishou | 后台相对前台 |
|---|---:|---:|---:|
| 存活 HClass 数 `N` | 76,848 | 68,706 | -8,142 |
| HClass 浅层堆 | 6,762,624 B（6.449 MiB） | 6,046,128 B（5.766 MiB） | -716,496 B |
| 四字段非默认 owner 并集 `U` | 2,164（2.816%） | 2,155（3.137%） | -9（覆盖率 +0.321 个百分点） |
| 主对象 88 B→64 B 毛收益 `24N` | 1,844,352 B（1.759 MiB） | 1,648,944 B（1.573 MiB） | -195,408 B |
| 48 B sidecar 成本 `48U` | 103,872 B（0.099 MiB） | 103,440 B（0.099 MiB） | -432 B |
| 浅层净收益 `24N-48U` | 1,740,480 B（1.660 MiB） | 1,545,504 B（1.474 MiB） | -194,976 B（-0.186 MiB，-11.2%） |

**结论**：后台 full-GC 后可回收的死亡 HClass 不再进入收益人口，绝对净收益因此下降，但存活 HClass 的稀疏字段覆盖率仍仅 3.137%，远低于 50% break-even，**不改变强 sidecar 方案可行结论**。上述净收益已包含 TaggedArray 对象头、4 个槽和 8 B 对齐；未包含 Region 尾部碎片、allocator/RSS/PSS 变化及 GC 扫描时间，这些仍需实现后 A/B 实测。后台存活态浅层模型置信度高；`DependentInfos=0` 仍是 JIT-off 样本事实，不外推到 JIT-enabled 产品。