# 归档方案索引（不可行 / 低置信 / 需人工判断）

本目录归档**置信度 <60%** 的方案，等待人工判断。置信度 ≥60% 的方案已提取到 `../feasible-proposals/`。分三类：

- `rejected.md` —— **不可行/已否决**：事实基础被源码推翻、推导被复核否定，或人工审视否决；
- `needs-human-judgment.md` —— **需人工判断**：方向成立但收益未定；
- `competitor-memory-sweep.md` —— **竞品降内存措施迁移排查**（V8/JSC/Hermes/SM × ArkTS 判定矩阵）。

分类依据：`ets_runtime` 源码核验 + Top13 快照（`team_interop/analysis/top13-jit-off/top13-jit-off-estimates.csv`、`team_interop/analysis/top13-memory-landscape/top13-memory-node-names.csv`）+ 各文档 `HERMES REVIEW APPENDIX 2026-08-12` 复核结论。

## 总判断表（置信度 <60% / 已否决）

| 原方案 | 原声称收益 | 判断 | 一句话依据 |
|---|---|---|---|
| ConstantPool 稀疏化 | 250–280 MiB | 不可行 | 「无对象边」是 Hole 上界，非 Hole；容量取决于最高访问 index |
| Method 瘦身（裁剪 JIT 字段） | 25–37 MiB | 不可行 | `Method` 无 machine_code/baseline_code 字段 |
| FunctionTemplate 瘦身（裁剪 JIT/调试字段） | 15–25 MiB | 不可行 | `FunctionTemplate` 仅 Method/Module/RawProfileTypeInfo/Length |
| ProfileTypeInfoCell JIT-off 整体裁剪 | 28.5 MiB | 不可行 | cell_0 由解释器 IC 反馈分配，非 JIT 专属（槽级裁剪见 detailed） |
| JIT 分档布局（56/88B 双档） | 4.27 MiB（140k） | 不可行 | 运行时物理布局分档使 visitor/compiled offset 失配 |
| JSFunction 辅助对象 side-table | 16–32 B/函数 | 不可行 | 把内联槽误当「已预分配对象」；Module 非 JIT-only |
| 内建/常用函数 Flyweight | 9×SIZE | 不可行 | JS 对象 identity 无法无缝替换成共享模板 |
| LexicalEnv 瘦身 | 1–2 MiB | 需人工判断 | 编译器侧，收益小 |
| JSObject inline slot 缩容 | 待插桩 | 需人工判断 | slack tracking 机制已有（`--enable-inline-property-optimization`），待查默认档位与 `(cap=4,used=0)` 成因 |
| Dictionary 模式对象优化（VM 侧开放寻址） | 5–10 MiB | 需人工判断 | 应用侧已并入 02 统一清单 A4；VM 侧需哈希表实测 |

人工审视否决（2026-08-15）：JSFunction 代码槽移除（布局冻结硬约束）、AccessorData 内联、TaggedArray trim、模块元数据压缩、ClassLiteral 惰性驻留、method_idx 缩减、共享单例 HClass——依据见 `rejected.md` §8–14。

## 已提取到 feasible-proposals（置信度 ≥60%）

| 方案 | 置信度 | 去向 |
|---|---|---|
| JSHClass side-table 外迁 | — | 升级为详细方案 `../detailed-proposals/jshclass-auxdata-sidecar/`（弱表设计改强 sidecar） |
| Native interop 惰性绑定 | — | 升级为详细方案 `../detailed-proposals/native-interop-lazy-binding/` |
| JSFunction code-slot / AccessorData 内联 / TaggedArray trim / 模块元数据压缩 / ClassLiteral / method_idx | — | 人工否决，见 `rejected.md` §8–13 |
| FunctionTemplate 按需创建 | 60% | 保留 `../feasible-proposals/11-functiontemplate-on-demand/` |
| ProfileTypeInfoCell 惰性分配 | 75% | 新增 `../feasible-proposals/15-profile-cell-lazy-allocation/` |

> **已实现方案（源码核验）**：原 `feasible-proposals/01`「JSHClass 零实例回收」的核心机制「Transitions 弱引用」经源码核验**已实现**（单后继弱引用 `js_hclass-inl.h:39-40` + 多后继 TransitionsDictionary 弱值 `transitions_dictionary.h:113-120`），无增量收益，故移除。遗留待办：溯源 81,113 零实例 HClass 的真实强引用来源（MegaICCache 裸指针 / RootHClass 缓存 / AOT）。

> **已放弃方案（人工评审）**：`指针压缩（JSHClass 局部）` 与 `零 size native pointer 内联` 两方案已放弃，对应 proposal 文档（`pointer-compression-proposal.md`、`zero-size-native-pointer-elimination-proposal.md`）已删除。

## 数据口径提醒（防止再次误用）

1. 13 份 `tmp-napi-scan/*.heapsnapshot` 由旧版 translator 生成，节点名（`constant_pool`、`hclass` 等）与官方 translator（`ArkInternalConstantPool`、`HiddenClass(NonMovable)`）不同，V1/V2 边语义也不同（`rawheap-analysis-method.md` 复核）。
2. 任何「无字段边 = 空槽 = 可回收」的换算都不成立：快照仅在槽位持有堆对象时产生边，原始值（Smi/double/boolean/Undefined/Hole）槽位不产生边。
3. 堆内合计不得把覆盖同一对象链的方案相加（如 native 惰性绑定与编译期裁剪同属 Bucket C 存量）。
4. 净收益需 clean A/B 实测 PSS/heap，静态快照只能给出确值/下界/上界，不能给出「可回收量」的期望值。

---

## 其他方向缺口

除上述方案外，还存在若干「已有方案未覆盖」的方向（ArkInternalArray 本体承载、JSSharedObject、PrototypeHandler 等），详见 [opportunity-gaps.md](./opportunity-gaps.md) 与 [competitor-memory-sweep.md](./competitor-memory-sweep.md)。