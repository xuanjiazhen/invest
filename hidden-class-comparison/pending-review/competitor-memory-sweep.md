# 竞品降内存措施迁移排查（V8 / JSC / Hermes / SpiderMonkey × ArkTS）

对四个主流 JS 引擎历史上公开的降内存措施逐项排查在 ArkTS VM 的可迁移性。判定分四类：**已具备**（ArkVM 源码已有）、**可迁移**（形成或对应方案）、**受约束阻塞**（与硬约束冲突）、**不适用**（场景不存在）。

**硬约束**（人工审视确定）：① JSFunction 布局冻结（三方应用按函数指针 memcpy 内存布局）；② ≤6G 设备宏编译关闭 AOT/JIT（分档载体）；③ 框架侧（ArkUI stateMgmt 等）不改。

## 排查矩阵

### V8

| 措施 | V8 做法 | ArkTS 现状 / 判定 |
|---|---|---|
| 指针压缩（tagged 4B） | 64 位堆上全量 4B tagged | **受约束阻塞**：架构级改造（GC/编译器/快照全线），OpenHarmony 未启用；JSHClass 局部压缩已评估后放弃（见 pending-review 已放弃记录） |
| 惰性反馈向量（lazy feedback vectors） | 反馈结构延迟到函数预热后分配，冷函数零反馈驻留 | **待验证候选** → `../feasible-proposals/15-profile-cell-lazy-allocation/`；ArkVM 还需解决父 `ProfileTypeInfo + slotId` 定位与同 slot 共享 |
| 字节码冲刷（bytecode flushing） | GC 多轮未执行后释放冷函数字节码+反馈 | **部分已具备**：ArkTS 字节码在共享 JSPandaFile（mmap，非堆内），Method 包装对象 64 B×1.65M 随 abc 常驻；Method 无入边仅 5.43 MiB，冲刷收益有限，**不立项** |
| Map 去重 / slack tracking | 实例数固定后收缩 in-object 槽 | **已具备（可选开关）**：`--enable-inline-property-optimization`（附带 slack tracking，`js_runtime_options.cpp:232`）、`VisitTransitionAndUpdateObjSize`（`js_hclass-inl.h:358`）、`isStartSlackTracking`（`js_function.h:452`）。待判点收窄为：产品档位默认是否开启、快照观测到的 `(cap=4, used=0)` 高频形态是否因未开启/未固化（对应 pending-review needs-human-judgment §2，插桩前置） |
| 共享只读堆 | ReadOnlyRoots 跨 isolate 共享 | **已具备**：`SharedReadOnlySpace`（`mem/heap.h:803-805,1157`）跨 VM 共享 |
| 原地字符串驻留（in-place internalization）+ string forwarding table | 驻留去重免拷贝、跨线程共享字符串 | **部分可迁移**：常量字符串已 `GetOrInternString`；动态短串未驻留 → `feasible-proposals/04-string-optimization/`（真实口径 126 MiB，短串 dedup 6–15 MiB 预估） |
| ExternalString（大字符串外部资源化） | >阈值字符串数据外置、按需 resource 化 | **已具备机制**：`CachedExternalString`（`string/base_string.h` 一带）；>1K 大串 32.63 MiB 属应用侧使用问题 → `feasible-proposals/02-app-side-consolidated/` A6 |
| Map/DescriptorArray 弱依赖（dependent_code 弱表） | 优化代码依赖弱收集 | **已具备等价**：Transitions 弱引用、DependentInfos 弱载荷（js_hclass 体系） |
| FeedbackVector 槽位压缩 / 共享 | 反馈槽 Smi 化、共享向量 | **可迁移（并入 15）**：cell 惰性后剩余 cell 的 Value 数组布局可另行评估，暂不单列 |

### JSC

| 措施 | JSC 做法 | ArkTS 现状 / 判定 |
|---|---|---|
| Butterfly COW（数组存储写时复制） | 数组 backing 跨实例共享、写时复制 | **部分已具备**：字面量数组 COW（`ENABLE_COW_ARRAY`，≤10 元素 NON_MOVABLE 共享）；detailed `constantpool-shared-literal` 仅评估对象字面量外置 backing COW，不修改数组路径，也不计入既有数组 COW 收益 |
| UnlinkedCodeBlock 共享 | 字节码元数据跨闭包共享 | **已具备等价**：JSPandaFile/abc 跨 VM 共享 + FunctionTemplate 共享 |
| Structure 去重 / transition 压缩 | 形状元数据共享 | **已具备**：transition 链 + root HClass 缓存；增量见 `14-layoutinfo-attr-packing`（Attr 槽压缩）与 detailed auxdata-sidecar；**DescriptorArray 家族共享**已立项迁移评估 → `feasible-proposals/16-layoutinfo-sharing/`（内容去重上界 54.0 MiB + 链共享 2.35 MiB） |

### Hermes

| 措施 | Hermes 做法 | ArkTS 现状 / 判定 |
|---|---|---|
| 编译期全量字符串驻留（IntRef） | 所有字符串编译期驻留、运行期零去重 | **部分可迁移**：Hermes 靠预编译闭环；ArkTS 动态串仍需运行期 intern-on-create（限长阈值+容量上限）→ 并入 04 |
| 预编译字节码 mmap 共享 | 多实例进程共享只读字节码 | **已具备**：abc/JSPandaFile 机制等价 |

### SpiderMonkey

| 措施 | SM 做法 | ArkTS 现状 / 判定 |
|---|---|---|
| nursery 整形对象不晋升 | 小对象短命回收 | GC 策略层，与 09（已人工否决：GC 调整复杂）同类，**不迁移** |
| malloc'd 大数组存储 | 大数组数据走系统分配器 | ArkTS native buffer 路径已有（js_native_pointer），治理属应用侧（opportunity-gaps 大 buffer 项） |

## 未落地提案与研究方向（2026-08-24 深度排查）

以下为业界竞品**尚未进入生产**的内存优化提案/实验/研究，逐项分析可迁移性。来源覆盖 v8-dev mailing list、Node.js issue tracker、TC39 proposal、WebKit Bugzilla、SpiderMonkey newsletter/blog、Hermes/React Native blog、学术论文。

### 排查矩阵

| # | 技术 | 引擎 | 状态 | 解决什么问题 | ArkTS 判定 | 拒绝/接受理由 |
|---|------|------|------|--------------|------------|---------------|
| 1 | Hybrid Arena + GC via SPI | V8 | v8-dev 提案（未接受） | 嵌入方通过 SPI 告知 GC 分配业务上下文，短命 arena 友好分配绕过 tracing GC | ❌ **拒绝：过于 speculative** | 无实现参考、无量化数据、需 GC 基础架构重造；概念上对低内存设备的 GC 压力优化有启发，但距可评估的工程方案尚远 |
| 2 | Isolate Groups / Multi-Cage | V8/Node | 实验性 flag（Node #55735） | 每个 isolate group 独立 4 GB 指针压缩 cage，使多 isolate 进程启用指针压缩（~50% 堆降） | ❌ **拒绝：受指针压缩约束阻塞** | ArkVM 未启用指针压缩（已标记为架构级改造）；Multi-Cage 是指针压缩在多 VM 场景的前置条件，不改变指针压缩本身被阻塞的判定 |
| 3 | TC39 Shared Structs / Shared Arrays | V8（TC39 Stage 2→3） | Chrome M108 实验实现（`--js-staging`） | 跨 isolate 共享不可变对象，消除多 worker 间的数据复制 | ✅ **已具备等价** | ArkVM 已有 shared heap / sendable 对象机制；TC39 提案是 API 标准化，不新增底层内存优化能力 |
| 4 | V8 Sandbox Trusted Space re-layout | V8 | 进行中（安全驱动） | 将字节码/代码元数据/Wasm 可信对象从沙箱移入 Trusted Space（经间接指针表） | ❌ **不适用** | 安全驱动的堆重构，间接指针表本身**增加**内存开销；ArkVM 无 Chrome 沙箱威胁模型 |
| 5 | JSC Structure-count reduction at startup | JSC | WebKit Bug 153399（8 年未关闭） | 启动期减少 Structure 实例数（用 `addPropertyWithoutTransition()` 和结构表共享） | ⚠️ **低优先监测** | 概念上可与 layoutinfo-sharing 互补（同时减 hclass 数量和 LayoutInfo 份量）；但 bug 8 年未关闭暗示实现难度大或收益有限；建议跟踪 JSC 后续进展 |
| 6 | Gecko/SpiderMonkey shared string buffer | SpiderMonkey | Bug 1892253（进行中） | JS 引擎与 DOM 层共享单一字符串 buffer，消除 JS/native 边界的字符串复制 | ○ **部分已被覆盖** | 概念相关（跨层字符串零拷贝），但 ArkTS 的等价场景（跨 VM 字符串共享）已在 `detailed-proposals/constantpool-shared-literal/` sub-A 中评估 |
| 7 | Nursery string pretenuring redesign | SpiderMonkey | 设计讨论（wingolog 2025 + Bug 1635087） | 重新设计字符串在 nursery 中的分配/晋升策略，减少长命字符串的 nursery churn | ❌ **拒绝：GC 调整类** | 与已否决的 09（TaggedArray trim: "GC 调整复杂"）同类；ArkVM 字符串已通过 intern 进 old space，pretenuring 争议对 ArkVM 收益不明 |
| 8 | Static Hermes（AOT+JIT） | Hermes | 提案/路线图（V1 未包含） | 向 Hermes 添加 AOT 编译和 JIT，提升性能 | ○ **方向验证** | 非内存优化——Hermes 内存优势恰来自 interpreter-only 设计；反向**验证**了 ≤6G 档关 AOT/JIT 省内存方向正确 |
| 9 | Dynamic Code Compression | 学术（Samsung Research 论文） | 论文（无引擎采纳） | 压缩引擎堆内的 JS 源/描述符，按需解压 | ❌ **拒绝：热路径代价致命** | 43.3% 堆降声称含源码压缩（ArkTS abc 已 mmap 不在堆内）；剩余的元数据压缩在 IC/属性查找热路径上需解压，代价不可接受；无引擎实践验证 |
| 10 | Optimal heap limits | 学术（ACM 论文） | 论文 | 基于 advisor 的动态堆限制调整 | ❌ **拒绝：GC 调整类** | ~16% 内存降属 GC 调参范畴；ArkVM 已有堆限制启发式（`ecma_param_configuration.h`）；与 09 同类否决 |

### 排查方法与来源清单

| 来源类型 | 具体地址 | 覆盖内容 |
|----------|----------|----------|
| V8 官方博客 | `v8.dev/blog` | 已落地方案的历史脉络 |
| V8 邮件列表 | `groups.google.com/g/v8-dev` | 提案/设计讨论（含 Hybrid Arena+GC proposal） |
| Node.js issue | `github.com/nodejs/node/issues/55735` | Isolate Groups 集成讨论 |
| TC39 proposal | `github.com/tc39/proposal-structs` | Shared Structs 标准化进展 |
| Chrome Status | `chromestatus.com/feature/5158145752563712` | 实验性 flag 状态 |
| V8 源码 sandbox | `chromium.googlesource.com/v8/v8/+/src/sandbox/README.md` | Sandbox/Trusted Space 设计 |
| WebKit Bugzilla | `bugs.webkit.org/show_bug.cgi?id=153399` | JSC Structure 数量减少 |
| SpiderMonkey newsletter | `spidermonkey.dev/blog` | GC 改进、shared string buffer |
| wingolog blog | `wingolog.org/archives/2025/02/09/...` | Nursery/pretenuring 设计讨论 |
| React Native blog | `reactnative.dev/blog/2025/10/08/react-native-0-82` | Hermes V1 / Static Hermes 路线图 |
| Samsung Research | `research.samsung.com/research-papers/...` | Dynamic Code Compression 论文 |
| ACM Digital Library | `dl.acm.org/doi/10.1145/3563323` | Optimal heap limits 论文 |

### 搜索覆盖限制

- **V8 Gerrit**（`chromium-review.googlesource.com`）不被搜索引擎索引，patch 级内存工作无法通过 web 搜索枚举；但 patch 级优化通常已体现在 v8-dev 讨论或 blog 中，提案级覆盖已由上述来源保证；
- **JSC 2024-2026** 无公开的堆重设计提案——JSC 内存工作以 Bugzilla 增量追踪为主，无大方向公告；
- **小众引擎**（QuickJS/Bun/Deno/workerd）未单独搜索——其内存优化通常限于指针压缩或简单堆收缩，核心技术类别已在现有 sweep 中覆盖。

## 结论

### 已落地方案排查结论

1. **本轮新增可迁移项 1 个**：V8 惰性反馈向量 → 并入 cell 详细方案阶段一（机制现成，约 30 人日独立交付，收益按消除率折算，上界 28.5 MiB）；
2. **确认已具备 5 项**（只读堆共享、abc 共享、transitions 弱引用、字面量数组 COW、ExternalString 机制）——后续提案不得重复计入这些方向的收益；
3. **受硬约束阻塞 2 项**：指针压缩（架构级）、JSFunction 布局类措施（07 已否决）；
4. **保持待判 1 项**：slack tracking 的产品化利用（ArkVM 已实现该机制但由 `--enable-inline-property-optimization` 开关控制——待确认默认档位与 `(cap=4, used=0)` 高频形态的成因，属插桩可查），这是本轮排查后唯一建议继续跟进的调查点；
5. 字节码冲刷在 ArkTS 的等价物（Method/常量池驻留）经核算收益 ≤5.43 MiB，不立项。

### 未落地提案排查结论（2026-08-24）

6. **10 项候选全部完成逐项分析**：6 项拒绝（含明确理由：过于 speculative / 受指针压缩阻塞 / 安全驱动不适用 / GC 调整类 / 热路径代价 / GC 调参）、2 项已具备等价（shared structs / shared string buffer）、1 项方向验证（Static Hermes 反向印证 ≤6G 关 JIT 方向）、1 项低优先监测（JSC Structure-count reduction，Bug 153399）；
7. **无新增可迁移项**——未落地提案中无适合 ArkVM 当前约束条件下立项的新技术方向；
8. **监测项唯一**：JSC Bug 153399（`addPropertyWithoutTransition` 减少启动期 Structure 创建）与 layoutinfo-sharing 方案在概念上互补（一个减 hclass 数量、一个减 LayoutInfo 份量），但 JSC 自身 8 年未关闭该 bug，暗示收益/难度比可能不理想，建议仅跟踪。
