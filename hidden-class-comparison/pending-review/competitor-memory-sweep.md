# 竞品降内存措施迁移排查（V8 / JSC / Hermes / SpiderMonkey × ArkTS）

对四个主流 JS 引擎历史上公开的降内存措施逐项排查在 ArkTS VM 的可迁移性。判定分四类：**已具备**（ArkVM 源码已有）、**可迁移**（形成或对应方案）、**受约束阻塞**（与硬约束冲突）、**不适用**（场景不存在）。

**硬约束**（人工审视确定）：① JSFunction 布局冻结（三方应用按函数指针 memcpy 内存布局）；② ≤6G 设备宏编译关闭 AOT/JIT（分档载体）；③ 框架侧（ArkUI stateMgmt 等）不改。

## 排查矩阵

### V8

| 措施 | V8 做法 | ArkTS 现状 / 判定 |
|---|---|---|
| 指针压缩（tagged 4B） | 64 位堆上全量 4B tagged | **受约束阻塞**：架构级改造（GC/编译器/快照全线），OpenHarmony 未启用；JSHClass 局部压缩已评估后放弃（见 pending-review 已放弃记录） |
| 惰性反馈向量（lazy feedback vectors） | 反馈结构延迟到函数预热后分配，冷函数零反馈驻留 | **可迁移** → `detailed-proposals/profile-type-info-cell-jitfree/` 阶段一（Empty→cell 转换机制已存在） |
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
| Butterfly COW（数组存储写时复制） | 数组 backing 跨实例共享、写时复制 | **部分已具备**：字面量数组 COW（`ENABLE_COW_ARRAY`，≤10 元素 NON_MOVABLE 共享）；扩容后的数组 backing 不 COW → 对应 detailed `constantpool-shared-literal` 子方向 B（对象字面量 backing COW 化） |
| UnlinkedCodeBlock 共享 | 字节码元数据跨闭包共享 | **已具备等价**：JSPandaFile/abc 跨 VM 共享 + FunctionTemplate 共享 |
| Structure 去重 / transition 压缩 | 形状元数据共享 | **已具备**：transition 链 + root HClass 缓存；增量见 `14-layoutinfo-attr-packing`（Attr 槽压缩 23.17 MiB）与 detailed auxdata-sidecar |

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

## 结论

1. **本轮新增可迁移项 1 个**：V8 惰性反馈向量 → 并入 cell 详细方案阶段一（机制现成，约 30 人日独立交付，收益按消除率折算，上界 28.5 MiB）；
2. **确认已具备 5 项**（只读堆共享、abc 共享、transitions 弱引用、字面量数组 COW、ExternalString 机制）——后续提案不得重复计入这些方向的收益；
3. **受硬约束阻塞 2 项**：指针压缩（架构级）、JSFunction 布局类措施（07 已否决）；
4. **保持待判 1 项**：slack tracking 的产品化利用（ArkVM 已实现该机制但由 `--enable-inline-property-optimization` 开关控制——待确认默认档位与 `(cap=4, used=0)` 高频形态的成因，属插桩可查），这是本轮排查后唯一建议继续跟进的调查点；
5. 字节码冲刷在 ArkTS 的等价物（Method/常量池驻留）经核算收益 ≤5.43 MiB，不立项。
