# JSHClass 分析上下文索引

本文档汇总 JSHClass（ArkVM Hidden Class）分析的全部本地上下文，供其他大模型/协作者接力分析。

生成时间：2026-07-30

---

## 1. 调研仓库

**GitHub**：`git@github.com:xuanjiazhen/invest.git`

**本地路径**：`D:\docker\invest`

**当前分支/HEAD**：`main` / `a76975f9b94eb7bfd257b74e4f033ea4f41f0989`

**远程**：`origin -> git@github.com:xuanjiazhen/invest.git`

**仓库规范**：`D:\docker\invest\AGENTS.md`

核心约束：
- index.html 只索引 HTML slides，不索引 .md
- 最终产物禁止过程性内容（合并、原本、此前、改为、修订自等关键词）
- 调研材料只陈述可由来源直接核验的事实

**dirty state**：工作区有 ` M hidden-class-comparison/plan.md` 未提交修改；`?? ai_design/` 未跟踪

---

## 2. hidden-class-comparison 目录文件清单

文档分三层：`detailed-proposals/`（人工筛选可行并完成多角色评审的详细方案）、`feasible-proposals/`（置信度 ≥60% 的候选方案）、`pending-review/`（不可行/低置信归档与方向缺口）。

| 文件/目录 | 用途 |
|---|---|
| `plan.md` | 原始需求 |
| `jshclass-layout-analysis.md` | **核心报告**：JSHClass 逐字段布局、竞品对比 |
| `jshclass-layout-review.md` | JSHClass AuxData Sidecar 完整设计（detailed-proposals/jshclass-auxdata-sidecar 的设计母本，含逐应用模型与源码证据附录） |
| `constantpool-full-analysis.md` | ConstantPool 全链路解析（13 号方案的背景） |
| `rawheap-analysis-method.md` | rawheap→heapsnapshot 取数方法与口径 |
| `lazy-binding-app-side-guide.md` | native interop 惰性绑定的应用侧配套指南 |
| `top13-heap-optimization-opportunities.md` | Top13 堆构成全景数据源（含 HERMES 复核标记，汇总数字不得引用） |
| `hidden-class-comparison-slides.html` | 交互幻灯片 |
| `detailed-proposals/` | 4 个详细方案（auxdata-sidecar / profile-cell-jitfree / native-interop-lazy-binding / constantpool-shared-literal），各含 01-背景 02-需求 03-方案设计 04-review-log |
| `feasible-proposals/` | 02/03/04/07/08/09/10/11/12/13/14 号候选方案（各含 4 件套） |
| `pending-review/` | rejected / needs-human-judgment / opportunity-gaps / competitor-memory-sweep |
| `evidence/` | 快照复算冻结数据（auxdata 联合分布、constantpool census、string/array census、layout 去重 census） |
| `scripts/` | 快照统计脚本 |

### 各级标题速览

**jshclass-layout-analysis.md** 三大部分：
- 第一部分：JSHClass 布局全景（整体结构->逐字段详解，每个字段按产生阶段/消费场景/用户可感知行为/证据四维度展开）
- 第二部分：竞品对比（V8/JSC/Hermes，总体差距汇总表，各竞品详解）
- 第三部分：优化方案 A-F（ProtoChange合并/DependentInfos外移/EnumCache外移/Transition树/PointerCompression/JSApiFunction裁剪）+ 京东场景效果汇总

**detailed-proposals/*/03-方案设计.md** 统一按《架构特性设计模板》组织：来源与价值 → 影响分析 → 竞品对比 → 设计方案 → DFX → 可信分析 → DT 用例 → 结论。

---

## 3. 关键事实（已确立，来自源码）

### 3.1 JSHClass 自身大小：88B

- 布局定义：`js_hclass.h:2214-2226`
- 对齐宏：`ecma_macros.h:283-284` -> `DEFINE_ALIGN_SIZE(LAST_OFFSET)` -> `JSHClass::SIZE = 88`
- **不包含** `DEFAULT_CAPACITY_OF_IN_OBJECTS = 4` 的对象内属性槽（`js_hclass.h:412`）
- 此前错误地将 4x8B=32B 加到了 88B 上得到 120B

### 3.2 字段布局（偏移从 ACCESSORS 宏精确计算）

```
偏移    大小    字段
 0       8B    TaggedObjectHeader
 8       4B    BitField (uint32_t)
12       4B    BitField1 (uint32_t)
16       8B    Proto
24       8B    Layout
32       8B    Transitions
40       8B    Parent
48       8B    ProtoChangeMarker
56       8B    ProtoChangeDetails
64       8B    EnumCache
72       8B    DependentInfos
80       8B    BitField2 (uint64_t)
-- 88B
```

### 3.3 Heap Snapshot self_size 取值链路

`js_hclass.h:2226` -> `DEFINE_ALIGN_SIZE(LAST_OFFSET)` -> `JSHClass::SIZE = 88`

Snapshot 序列化：
- `heap_snapshot_json_serializer.cpp:124` -> `writer->WriteNumber(node->GetSelfSize())`
- `heap_snapshot.cpp:677-679` -> `selfSize = obj->GetSize()`
- `js_hclass-inl.h:276-278` -> `default: size = GetObjectSize()`（JSHClass 不命中特殊 case）

`88 / 1024 = 0.0859375 KiB`，保留两位小数 -> **0.09 KB**

Snapshot 的 `self_size` 是节点浅层大小，不包含指向的 Layout、Transitions、EnumCache 等独立堆对象。

### 3.4 JSHClass 分配时使用 JSHClass::SIZE

- `object_factory.cpp:149` -> `uint32_t classSize = JSHClass::SIZE;`
- `object_factory.cpp:161` -> 同上
- `object_factory.cpp:179` -> 同上
- `object_factory.cpp:479` -> 同上

### 3.5 SemiSpace 与 Region

- `ecma_param_configuration.h:90` -> `minSemiSpaceSize_ = 2_MB`（配置上限，非启动即占用）
- `mem/linear_space.cpp:463-470` -> `SemiSpace::Initialize()`：分配一个 `DEFAULT_REGION_SIZE` 的 Region
- `mem/mem.h:71` -> `DEFAULT_REGION_SIZE = 1U << REGION_SIZE_LOG2` = 256 KiB
- SemiSpace 从 256 KiB 起步，按 Region 粒度扩展，不归单个 JSHClass 所有

### 3.6 JSApiFunction 双宏路径

- `js_function.h:207-209` -> `JSApiFunction : JSFunctionBase`
- `js_function.h:256` -> `JSFunction : JSApiFunction`
- 双宏 `ENABLE_API_FUNCTION_OPTIMIZATION && ENABLE_MEMORY_OPTIMIZATION` 控制瘦身版

### 3.7 京东场景数据

- 观测到 140,000+ 个 JSHClass
- 当前基线：`140,000 x 88B = 12.32 MiB`
- 各方案毛节省（仅内联字段删除，未扣 side table）：
  - 方案A（ProtoChange 16B）：1.22 MiB
  - 方案B（DependentInfos 8B）：0.61 MiB
  - 方案C（EnumCache 8B）：0.61 MiB
  - 方案A+B：1.83 MiB
  - 方案A+B+C：2.44 MiB
  - 方案E（Pointer Compression 理论）：2.75 MiB（上限）

---

## 4. 源码仓库

### 4.1 OpenHarmony ets_runtime（主分析源）

**本地路径**：`D:\docker\openharmony-standard`

**获取方式**：repo sync（manifest 使用 gitcode remote）

**manifest 路径**：`D:\docker\openharmony-standard\.repo\manifests\default.xml`

**远程**：
```xml
<remote fetch="https://gitcode.com/openharmony" name="gitcode" review="https://gitcode.com/openharmony/"/>
<default remote="gitcode" revision="master" sync-j="4"/>
```

**ets_runtime 子仓库**：
- 项目 git：`D:\docker\openharmony-standard\.repo\projects\arkcompiler\ets_runtime.git`
- 工作树：`D:\docker\openharmony-standard\arkcompiler\ets_runtime`
- 远程：`gitcode -> https://gitcode.com/openharmony/arkcompiler_ets_runtime`
- 分支：`master`
- HEAD（工作树 .git/HEAD 内容）：`4ad6583a30981259b857579c61b5cc83b3530381`

**注意**：`D:\docker\openharmony-standard` 根目录自身不是 Git 仓库，各子项目独立。git 命令在 Windows 下访问 .git 可能因权限问题（WinError 1920）失败。

### 4.2 分析涉及的核心源文件

所有路径相对于 `D:\docker\openharmony-standard\arkcompiler\ets_runtime\ecmascript\`：

| 文件 | 大小 | 关键行 |
|---|---|---|
| `js_hclass.h` | 106,944 B | L412 (DEFAULT_CAPACITY_OF_IN_OBJECTS), L2214-2226 (ACCESSORS+DEFINE_ALIGN_SIZE) |
| `js_hclass-inl.h` | 21,140 B | L221-283 (SizeFromJSHClass) |
| `js_hclass.cpp` | 81,265 B | |
| `object_factory.cpp` | 282,978 B | L145-185 (NewEcmaHClass, classSize = JSHClass::SIZE) |
| `object_factory.h` | 61,016 B | |
| `shared_object_factory.cpp` | 50,121 B | |
| `ecma_macros.h` | 66,701 B | L283-284 (DEFINE_ALIGN_SIZE) |
| `js_function.h` | 30,296 B | L207-209 (JSApiFunction), L256-501 (JSFunction) |
| `ecma_param_configuration.h` | -- | L90/119/148 (minSemiSpaceSize_), L384 (字段声明) |
| `mem/tagged_object.h` | 3,522 B | |
| `mem/region.h` | 35,074 B | L939 (DEFAULT_REGION_SIZE/2), L1059-1060 (可用大小) |
| `mem/linear_space.cpp` | 22,421 B | L147 (Expand), L463-470 (SemiSpace::Initialize) |
| `mem/mem.h` | -- | L71 (DEFAULT_REGION_SIZE = 1U << REGION_SIZE_LOG2) |
| `mem/heap.cpp` | -- | L250 (capacity计算) |
| `dfx/hprof/heap_snapshot.cpp` | 62,832 B | L672-690 (HandleBaseClassNode), L946/1002/1037 (GenerateNode selfsize) |
| `dfx/hprof/heap_snapshot.h` | 23,774 B | |
| `dfx/hprof/heap_snapshot_json_serializer.cpp` | 16,127 B | L70-79 (node_fields), L114-130 (SerializeNodes) |
| `dfx/hprof/heap_snapshot_json_serializer.h` | 4,982 B | |

### 4.3 OpenHarmony Docs

**本地路径**：`D:\docker\code\openharmony-docs`

**HEAD**：`f7e4f43487bb76304c3fb44daceeac9aad86ecaf`

**远程**：`origin -> https://gitcode.com/openharmony/docs.git`

### 4.4 wikishare（团队互通设计）

**本地路径**：`D:\docker\code\wikishare\team_interop`

**HEAD**：`3f9043ca0518238cdc2fe4cc882bc71cc64744ef`

**远程**：`origin -> git@gitcode.com:Cangjie/wikishare.git`；`fork -> https://gitcode.com/xuanjz/wikishare.git`

**dirty**：有 `team_interop/` 下的未跟踪文件

### 4.5 OpenHarmony 构建 Docker

**镜像**：`oh-standard-fixed`（基于 official:3.2 + 追加 autotools）

**容器**：`oh-build-rk3568`（Exited (0)，8天前退出）

---

## 5. 相关但独立的分析

### 5.1 NapiDefineClass 元数据分析

**位置**：`D:\docker\invest\napi-metadata-memory\`

**关键文件**：
- `report.spec.md`：NapiDefineClass 调用链、结构体大小、SemiSpace 增长模式、竞品对比
- `plan.spec.md`：原始计划
- `napi-metadata-memory-slides.html`：演示幻灯片

**结论要点**：
- SemiSpace `minSemiSpaceSize_` 配置为 2 MB，但启动只分配一个 256 KiB Region
- Region 粒度 256 KiB，SemiSpace 按需扩展
- NapiDefineClass 元数据膨胀根因：SemiSpace minSemiSpaceSize=2MB 占比 98%，而非 JSHClass 字段本身

### 5.2 已识别的待办（plan.md 未提交修改）

plan.md 工作区新增一行：要求不局限 JSHClass，整体发掘低内存设备上的其他优化空间。

---

## 6. Heap Snapshot 数据

- 本地未找到 `.heapsnapshot` / `.rawheap` / `.heap` / `.hprof` 文件
- 分析基于源码推导，未对照原始 Snapshot 节点数据
- Snapshot 的 `self_size` 字段语义：浅层大小（不包含引用的独立对象）
- 列定义：`{"node_fields":["type","name","id","self_size","edge_count","trace_node_id","detachedness","native_size"]}`

---

## 7. 已完成的 Git 提交（hidden-class-comparison）

```text
a76975f docs: estimate JSHClass savings for JD workload
16e4688 jshclass-layout: 按TODO意见全面重写 (用户视角+代码示例+V8细节+兼容性场景)
0c0dd6a hidden-class: 新增 JSHClass 逐字段全景分析 + 6方案优化矩阵 (V8/JSC/Hermes对标)
013b8ac hidden-class: 新增 EnumCache 惰化方案 (side table + 组合优化)
eef00b8 hidden-class: 新增 ENABLE_API_FUNCTION_OPTIMIZATION 路径分析 (JSApiFunction瘦身)
f650ae9 新增 Hidden Class 对比 (JSHClass vs V8 Map) -- 字段布局、Transition、优化建议
```

---

## 8. 已知的口径差异（重要，避免接力时重复出错）

1. JSHClass `self_size` 不等于 JSHClass 浅层大小 + 对象内属性槽
2. JSHClass `self_size` 不等于 SemiSpace / Region 容量
3. Side table 方案的毛节省须扣除表项/哈希桶占用才能得到净节省
4. 跨引擎比例（V8/JSC/Hermes）未在同配置下实测
5. 快照「无对象边」≠ 空闲槽：原始值（Smi/double/boolean/Hole）槽不产生边；引用归因按边统计会把共享对象（interned 字符串、16 B EmptyArray 单例）重复计入，人口统计必须按去重目标节点计算（见 `scripts/layout_dedup_census.py`）
6. **string 节点 self_size = 字符长度，不是对象尺寸**（`rawheap_dump.cpp:651-653` 写 `GetLength()`，内存区只存 8 B 类指针）：数据 83.03 MiB 之外另有 ~43 MiB 头部/对齐未入账，字符串收益模型必须按对象数 × (16 B 头 + align8(len)) 重算
7. `top13-heap-optimization-opportunities.md` 中被 HERMES 复核否决的汇总数字（ConstantPool 250–280 MiB、堆内合计 520–620 MiB 等）不得引用，该文件只作对象人口与分布数据源
8. Top13 快照为 JIT-off 采集：`DependentInfos=5` 等稀疏性观测不外推到 JIT-enabled 场景（JIT lazy-deopt 安装会写该槽）

<!-- BEGIN HERMES REVIEW APPENDIX 2026-08-12 -->
## 复核意见（2026-08-12）

- **结论（P1）**：本文只能作为历史接力索引，不能作为当前工作区、快照可用性或源码 revision 的权威状态；88B JSHClass 固定布局这一历史结论仍可由当前文件核对。
- **数据/源码事实**：本文 `CONTEXT.md:15,236-241` 记录旧 HEAD 且称未找到快照；当前 invest 为 `main@cba54b474da073f2e58791feeb5fd5e4e139300c`，`D:\docker\invest\tmp-napi-scan` 已有 13 份 `.heapsnapshot`。当前 repo 子仓本地 `refs/heads/master` 缺失，不能把 `refs/remotes/gitcode/master` 当作已检出源码 HEAD。
- **风险或反例**：本文混合不同日期、仓库和工作树状态，未为每条事实绑定采集时间、dirty state、translator 与源码 revision；下游按旧边语义或旧人口继续推导会产生版本漂移。
- **放行条件**：把仓库状态、目录清单、快照哈希和 translator 版本改为带日期的自动生成附录；分别记录 ets_runtime/runtime_core 可解析的检出 commit；历史状态明确标记“仅供追溯”。
<!-- END HERMES REVIEW APPENDIX 2026-08-12 -->

## 9. 2026-08-14 独立复核与新证据（本轮追加）

- **源码重验证**：4 个 detailed-proposals 的关键事实逐条对 `D:\docker\openharmony-standard` 源码复核通过，新增结论与修正已写入各方案 `04-review-log.md` 第 6 轮（cell Handle=PGO 专用可裁 16 B 档、auxdata 分阶段上库与 no-GC 入口清单、interop IC 失效机制具体化、constpool sub-A 上界 15.38 MiB）。
- **新增冻结数据**：`evidence/top13-string-array-census.json`（字符串 83.03 MiB 尺寸桶/持有方/无 sliced、数组引用归因）、`evidence/top13-layout-dedup-census.json`（Layout 去重 735,734 个 / 109.25 MiB / CP 字符串去重 15.38 MiB）。
- **新增方案 14**：LayoutInfo Attr 槽 8B→4B（对齐精算 23.17 MiB），见 §10 硬约束与 §12 升级记录。07（JSFunction 代码槽）次日在人工审视中被否决（布局冻结硬约束）。
- **文档清理**：被否决/被取代的历史提案（JIT 分档、函数 flyweight/辅助对象/单例 HClass、ConstantPool 稀疏化、EnumCache/ProtoChange/DependentInfos 单字段外迁、JSApiFunction 双宏分析、早期 120B 报告等 16 篇 + feasible 05/06 目录）已删除，否决理由保留在 `pending-review/`。


## 10. 硬约束（人工审视确定，2026-08-15）

1. **JSFunction 布局冻结**：JSFunction 相关布局的任何变化都被视为不兼容——部分三方应用直接基于函数对象指针按固定偏移拷贝内存布局，一旦修改应用无法工作（`pending-review/rejected.md` §8）。所有触碰 JSFunction 112 B 布局的方案一律不可行。
2. **≤6G 设备宏编译关闭 AOT/JIT**：产品分档决策，作为 cell 裁槽（detailed profile-cell）等编译期能力闭包方案的载体。
3. **框架侧（ArkUI stateMgmt 等）不修改**：应用侧行为改造统一汇总于 `feasible-proposals/02-app-side-consolidated/`。

## 11. 2026-08-15 人工 TODO 处理与新一轮挖掘

- **否决落地**：07（JSFunction 布局冻结硬约束）、08、09、10、12、13、共享单例 HClass 移入 `pending-review/rejected.md` §8–14；02/03 应用侧内容合并为 `feasible-proposals/02-app-side-consolidated/`（A1–A6 六项，含验证方法），框架侧不做。
- **设计追问闭环**：auxdata §4.1 修改前后布局对比、§4.9 弱表路线评估（EphemeronHashTable 底座可复用、+22–30 人日、净增益上限 ~4.6 MiB、维持强 sidecar）；14 对齐精算 23.17 MiB/21.2%（全量逐数组，N≤1 组零收益）。
- **插桩 patch 四份**：`detailed-proposals/native-interop-lazy-binding/05-插桩patch.md`（未读方法占比+descriptor 形态区分）、`detailed-proposals/constantpool-shared-literal/05-插桩patch.md`（worker 乘数+字面量归因）、`feasible-proposals/04-string-optimization/05-插桩patch.md`（dump 侧去重率+intern 命中率）、`feasible-proposals/11-functiontemplate-on-demand/05-插桩patch.md`（实例化率对账）。
- **关键口径修正**：快照 string 节点 `self_size` = 字符长度而非对象尺寸（`rawheap_dump.cpp:651-653`）；真实字符串堆占用 ≈126 MiB（2,281,554 对象 + ~43 MiB 头部/对齐），len≤16 占 54.3% 仅装 10.75 MiB 数据——已记入 §8 口径差异与 04 方案。
- **新方案 15**：ProfileTypeInfoCell 惰性分配——cell 在 DEFINEFUNC 即时分配（`interpreter-inl.cpp:1046,5106,5132` 等 7 处）而 99.9% 停留 cell_0；V8 lazy feedback vectors 迁移，Empty→cell 转换机制已存在（`js_function.cpp:1199-1205`），收益 = 消除率 × 28.5 MiB（当日稍后并入详细方案，见 §12）。
- **竞品措施迁移排查**：`pending-review/competitor-memory-sweep.md`——已具备 5+1 项（SharedReadOnlySpace、abc 共享、transitions 弱引用、字面量数组 COW、ExternalString 机制、slack tracking 可选开关）；可迁移新增 1 项（惰性反馈向量 → 15）；受约束阻塞 2 项（指针压缩、JSFunction 布局类）；唯一待跟进调查点为 slack tracking 的产品档位默认值与 `(cap=4,used=0)` 成因。
- **目录现状**：feasible = 02（应用侧汇总）/04/11/14/15；detailed = 4 方案（含两份插桩 patch）。

## 12. 2026-08-15 第二轮人工 TODO 处理

- **14 升级为详细方案**：`detailed-proposals/layoutinfo-attr-packing/`（四件套按架构模板重组，精算 23.17 MiB/21.2%，49 人日；与 auxdata-sidecar 同批版本 bump 可省 6–8 人日）。
- **15 并入 cell 详细方案**：`detailed-proposals/profile-type-info-cell-jitfree/` 重组为两阶段（阶段一惰性分配全档位通用、约 30 人日独立交付；阶段二三档裁槽），组合收益模型 `N×(32e+tier(1−e))`，合并工作量 84 人日。
- **应用侧改造指导**：`feasible-proposals/02-app-side-consolidated/02-改造指导.md`——A1–A6 逐项「识别（脚本+源码模式）→ 风险评估 → 改造模板 → 验证」，附 AI agent 执行规程（静态扫描模式清单 + 三分类风险评估 + patch 生成 + 自检）。
- **目录现状**：detailed = 5 方案（auxdata-sidecar / profile-cell 两阶段 / native-interop / constantpool / layoutinfo）；feasible = 02（含改造指导）/04/11。
