# Top13 应用堆内存优化机会全景（快照实证）

数据来源：Top13 应用各一份 rawheap 快照，经 `rawheap_translator` 转换为 `.heapsnapshot` 后逐节点统计。快照采集环境未启用 JIT（无 machine_code / baseline_code 节点）。

基线：

| 指标 | 数值 |
|------|------|
| heap_self 合计 | 1,728,014,825 B = 1,647.96 MiB |
| native_size 合计 | 320,749,045 B = 305.89 MiB |

按节点类型分布：array 661.01 MiB（40.11%）、native 398.76 MiB（24.20%）、closure 358.62 MiB（21.76%）、object 83.69 MiB（5.08%）、string 83.03 MiB（5.04%）、framework 59.42 MiB（3.61%）。

量化口径说明：快照仅在槽位持有堆对象时产生边。原始值槽位（Smi、double、布尔、Hole、Undefined 等）经掩码匹配后不产生边（`rawheap_translate.cpp:1822-1846`），因此"不持堆对象引用的槽位"是空闲槽位的上界。各章节已就此逐项说明该口径是否成立。

---

## 1. ConstantPool Hole 填充浪费（VM 改造）

| 指标 | 数值 |
|------|------|
| 证据 | 4,049 个 constant_pool，总容量 40,138,840 slot，实际使用 1,819,966 slot，填充率 4.53% |
| 浪费 | 292.35 MiB Hole 占位（占 heap_self 17.74%） |
| 极端案例 | jingdong 105 个池均为 524,360 B（cap=65,543），填充 0.04%–2.62% |

已解析槽位的目标构成（1,217,246 个 element 边）：method 54.2%、class_literal 17.4%、字符串 17.1%、js_object 6.4%、js_array 3.4%、tagged_array 1.3%。全部为堆对象，即常量池槽位承载的是对象引用而非内联原始值，因此未产生边的槽位即 Hole。

**问题根因**：ConstantPool 容量取自 abc IndexHeader.method_idx_size（`libpandafile/file.h:81-86`，上限 65,536 见 `file_format.md:294-296`），`ObjectFactory::NewConstantPool`（`object_factory.cpp:3535-3544`）用 Hole 初始化全部槽位。`ConstantPool::ComputeSize` 另加 `EXTEND_DATA_NUM=7` 与 `RESERVED_POOL_LENGTH=2`。单个方法只稀疏引用少量常量，但池按 abc 全局方法数分配，导致 95% 的槽位终身为 Hole。持有方为 `method` 的 ConstantPool 边与 VM 根（`ecma_vm.cpp:1925-1951` 的 `unsharedConstpools_`），生命周期与 abc 加载一致。

**优化方案**：
- A. 延迟分配：ConstantPool 初始分配小容量，按首次 resolve 时扩容（需修改 FindOrCreateUnsharedConstpool 路径）
- B. 稀疏索引：对 fill < 10% 的池采用 HashMap 存储，仅保存已 resolve 的条目
- C. 编译器侧：abc 打包时按实际引用重编号 method_idx，缩减 method_idx_size
- D. 跨 abc 共池：同一 HAP 内多 abc 共享一个 ConstantPool，按 module 偏移索引

**预估收益**：250–280 MiB（按 fill 率 10% 目标计算）

---

## 2. Native Interop 闭包过度分配（VM 改造 + 应用侧 + 编译器）

| 指标 | 数值 |
|------|------|
| 证据 | 959,398 个共享同一 native Method stub 的 JSFunction，128.22 MiB（7.78%） |
| 命名澄清 | 快照中 node_name 继承自 Method 名称"toJSON"，闭包自身 InlineProperty 字符串为实际函数名（hashCode / equals / CopyFrom / Clear / on / off 等） |
| 极端案例 | kuaishou 274,861 个 = 37.45 MiB，其中 175,025 个绑定在零实例类的 prototype 上 |
| 分类（13 应用全量核验） | A 匿名 accessor 绑定 32.96 MiB；B 有实例类原型方法 3.56 MiB；C 零实例类原型方法 61.47 MiB；D 非原型持有 30.22 MiB（其中同 hclass 冗余 **1.39 MiB**，修正自 18.78） |
| 每闭包附带 | HashField → 独立 js_native_pointer（40 B，ExternalPointer 指向共享 native 回调） |

**问题根因**：ANI/NAPI 互操作层在加载 abc 时为每个 native 类声明的每个方法创建独立 JSFunction 对象并绑定到 prototype。由于共享一个 native dispatch Method，每个 JSFunction 自身仅靠 ExternalPointer 和 InlineProperty 名称区分真实调用目标。当类从未被实例化时，prototype 上全部方法仍驻留堆中（bucket C = 61.47 MiB）；当同名方法被注入到多个同 hclass 实例（非 prototype 路径），出现逐实例冗余（bucket D redundant = **1.39 MiB**，修正自 18.78 —— 原值的分组键取到 `Properties` 数组的通用 hclass 而非宿主对象 hclass，导致跨类误合并，详见 `scripts/measure_lazy_binding_targets.py` 的分组键实现）。

**优化方案**：
- A. VM / ANI 层：**惰性原型绑定**——native 类加载时仅注册方法描述符到 hclass/prototype 的 lazy slot，首次属性访问时才实际分配 JSFunction（消除 bucket C）
- B. 应用 / 框架侧：将逐实例绑定（bucket D）提升为 prototype 共享方法，避免同 hclass 多个实例各持一份
- C. 编译器侧：abc 中标记从未引用的 native 类，加载时跳过其 prototype 初始化（与第 11 项联动）

**预估收益**：
- bucket C 惰性绑定：61 MiB
- bucket D 冗余提升至 prototype：**1.39 MiB**（实测，修正自 19）
- 合计约 **62 MiB**（取保守值；bucket A 的 33 MiB accessor 绑定需进一步拆分 getter/setter 共享度后确定）
- 方案 C（编译期零实例类裁剪）与方案 A 针对同一块 bucket C 存量，属两条实现路径，收益不可叠加，无独立数字

---

## 3. TaggedArray 余量（VM 改造）

| 指标 | 数值 |
|------|------|
| 证据 | 2,414,123 个 tagged_array（不含 constant_pool），总计 296.53 MiB |
| 无对象引用的槽位 | 147.85 MiB，按持有者拆分见下表 |

按持有边归属拆分 145.20 MiB（可定位持有者的部分）：

| 持有者 | 边名 | 数组数 | 空槽 MiB | 占比 | 性质 |
|--------|------|-------|---------|------|------|
| hclass | Layout | 735,184 | 58.81 | 40.5% | LayoutInfo 槽存属性描述符（原始值编码），非空闲容量 |
| js_map / js_shared_map | LinkedMap | 47,490 | 19.84 | 13.7% | LinkedHashMap 哈希桶预留，结构必需 |
| js_set | LinkedSet | 70,240 | 9.93 | 6.8% | 同上 |
| js_object | Elements | 62,105 | 30.74 | 21.2% | 空闲容量与原始值元素混合 |
| js_array | Elements | 73,968 | 7.30 | 5.0% | 空闲容量与原始值元素混合 |
| js_object | Properties | 80,867 | 3.77 | 2.6% | 属性区空闲容量 |
| global_env | element | 895 | 6.99 | 4.8% | VM 常量表槽位 |
| 其余 | — | — | 7.82 | 5.4% | 混合 |

**问题根因**：可优化部分集中在 Elements / Properties 两类存储数组——按 2x 策略扩容后不随元素删除收缩。LayoutInfo 与 LinkedHashMap 的空槽为结构必需，不可回收。Elements 的 38.04 MiB 中，存放数字等原始值元素的槽位同样不产生边，因此该值是空闲容量的上界，实际可回收量需运行时读取数组 length 字段确认。

**优化方案**：
- A. GC 后 trim：Concurrent Mark 阶段记录 Elements/Properties 数组的 length/capacity 比，Sweep 阶段对 ratio < 50% 的数组原地 shrink
- B. 空数组延迟分配：165,620 个独立分配的空数组（28.78 MiB）中，非共享 EmptyArray 单例的部分延迟到首次写入时分配
- C. 小数组内联：对 capacity ≤ 2 的 Elements 数组将 slot 嵌入持有者对象

**预估收益**：25–40 MiB（以 Elements + Properties 合计 41.81 MiB 为可回收基数，按 60%–95% 计）

---

## 4. Method 对象冗余（VM 改造 / 编译器）

| 指标 | 数值 |
|------|------|
| 证据 | 1,645,320 个 method 对象，尺寸统一 64 B，合计 100.42 MiB（6.09%） |
| 无入边 method | 88,927 个 = 5.43 MiB（占 5.4%），无任何 Method 边指向 |
| 分布 | douyin 327,309 个 / 19.98 MiB，weibo 253,253 个 / 15.46 MiB，wechat 136,847 个 / 8.35 MiB（其中 14,163 个无入边，占比最高 10.4%） |

**问题根因**：MethodLiteral resolve 时即分配 Method 对象，未被调用的函数同样占用 64 B。无入边的 88,927 个是仅被 ConstantPool 槽位持有、无 JSFunction 关联的部分。64 B 布局包含 JIT 相关字段，JIT 关闭时为零值。

**优化方案**：
- A. 惰性 Method 分配：首次 GetMethod 时才创建，未调用函数不分配（对应 5.43 MiB）
- B. Method 瘦身：JIT-off 配置裁剪 machine_code / baseline_code / profiling 字段，64 B 缩减至 40–48 B（对应 25–37 MiB）
- C. Method 共享：相同字节码入口 + 相同 ConstantPool 的 Method 复用同一实例（需 copy-on-write 保护 IC 状态）

**预估收益**：30–42 MiB（A + B 叠加）

---

## 5. 模块元数据膨胀（VM 改造 / 编译器）

| 类型 | 数量 | 体积 | 单体 |
|------|------|------|------|
| source_text_module_record | 272,094 | 43.59 MiB | 168 B |
| resolvedindexbinding_record | 1,179,149 | 26.99 MiB | 24 B |
| local_exportentry_record | 522,942 | 15.96 MiB | 32 B |
| indirect_exportentry_record | 118,136 | 3.61 MiB | 32 B |
| resolvedbinding_record | 101,067 | 2.31 MiB | 24 B |
| 其余 4 类 | 29,865 | 0.62 MiB | 16–32 B |
| **合计** | **2,223,253** | **93.08 MiB** | |

**问题根因**：ESM 模块系统为每个 import/export binding 分配独立堆对象。binding 记录数（1,179,149 + 101,067）是模块数（272,094）的 4.7 倍，且 24 B 的 ResolvedIndexBinding 中 16 B 为对象头——元数据开销超过承载内容。source_text_module_record 单体 168 B 为最大项，共 21 个字段槽位。

**优化方案**：
- A. Binding 表内联：resolvedindexbinding_record 以模块内 flat array 条目承载（每条 8 B 索引对，替代 24 B 独立对象），对应约 15 MiB
- B. ExportEntry 压缩：local/indirect_exportentry_record 的 LocalName/ExportName/ImportName 编码为 module_record 内的紧凑表，对应约 12 MiB
- C. 延迟解析：source_text_module_record 中 RequestedModules / StarExportEntries / Namespace 等字段在实际 import 时才分配
- D. 编译器侧：减少细粒度 re-export，降低 binding 记录基数

**预估收益**：30–45 MiB（A + B 为主，C 需运行时确认字段空置率）

---

## 6. JSHClass 单例率与零实例废弃（VM 改造）

| 指标 | 数值 |
|------|------|
| 证据 | 819,497 个 hclass = 68.77 MiB，平均 88 B |
| 单实例 hclass | 701,210 个（85.6%）仅有 1 个活实例 |
| 零实例 hclass | 81,113 个（9.9%）= 6.81 MiB，无任何活实例 |
| 分布 | douyin 133,401 个 / 11.20 MiB（零实例 12.5%），jrtt 零实例率最高 15.2%，wechat 最低 4.6% |
| 关联开销 | hclass 的 Layout 数组另占 58.81 MiB 不持堆对象引用的槽位（属性描述符原始值编码） |

**问题根因**：Transition 机制为每次 shape 变化创建新 hclass。85.6% 的 hclass 终身仅 1 个实例，说明元数据与实例数严重失衡。零实例 hclass 是 transition 链中的中间态，被父节点的 Transitions 表强引用而无法回收。

**优化方案**：
- A. 零实例回收：标记阶段统计 hclass 实例数，回收无实例且无 transition 子节点的 hclass（对应 6.81 MiB）
- B. Transition 表弱引用：Transitions 表以弱引用持有中间态 hclass，允许 GC 回收无实例的链节点
- C. Hclass 瘦身：详见 `jshclass-layout-review.md` 的方案矩阵，88 B 缩减至 48–64 B（对应 18–31 MiB）

**预估收益**：20–35 MiB（A + C 叠加）

---

## 7. FunctionTemplate 冗余（VM 改造）

| 指标 | 数值 |
|------|------|
| 证据 | 954,059 个 function_template = 36.39 MiB，尺寸统一 40 B |
| 持有方式 | 13/13 应用中 100% 由 cow_tagged_array 的 element 边持有，无悬空实例 |
| 分布 | douyin 179,395 个 / 6.84 MiB，jingdong 92,149 个 / 3.52 MiB，jrtt 69,145 个 / 2.64 MiB |

**问题根因**：FunctionTemplate 数量与函数声明数同阶（954,059 vs Method 1,645,320），由常量池侧的 COW 数组强引用，生命周期与 abc 加载一致而非与函数使用情况一致。40 B 为 TaggedObject 布局。

**优化方案**：
- A. 按需创建：仅在首次 NewJSFunction 时创建 template，未实例化的函数声明不分配
- B. Template 瘦身：40 B 字段中与 JIT / 调试相关的部分在 release 配置下裁剪
- C. 与第 11 项联动：编译期 DCE 减少函数声明总数，直接降低 template 基数

**预估收益**：15–25 MiB（按未实例化函数占比 40%–70% 计，需运行时确认实例化率）

---

## 8. ProfileTypeInfoCell 冗余（VM 改造）

| 指标 | 数值 |
|------|------|
| 证据 | 935,138 个 profile_type_info_cell_0 × 32 B = 28.54 MiB |
| 持有方式 | 全部由 JSFunction 的 RawProfileTypeInfo 边持有；持有者按模块聚集（douyin 中 `@live/live` 模块单独持有 40,171 个） |
| 分级情况 | cell_0（未收集到反馈）占 99.9%；cell_1 与 cell_n 合计仅数百个（douyin 878 个，jingdong 630 个） |
| 快照环境 | 无 machine_code / baseline_code 节点，即 JIT 未启用 |

**问题根因**：cell_0 表示尚未收集到类型反馈的状态，占比 99.9% 说明这些 cell 在本场景中从未承载数据。JIT 未启用时该 32 B 对象无实际用途。

**优化方案**：
- A. JIT-off 裁剪：Interpreter-only 配置下不分配 ProfileTypeInfoCell，JSFunction 的 RawProfileTypeInfo 槽置 Undefined
- B. 阈值分配：函数执行计数达到编译阈值后才分配 cell，避免 cell_0 长期空置
- C. 共享 cell_0：所有未收集反馈的函数共享同一 cell_0 单例，首次写入反馈时再分配独立实例

**预估收益**：28.5 MiB（JIT-off 场景全量消除）；JIT 开启场景下按 C 方案约 25 MiB

---

## 9. Native Pointer 持有的 off-heap 内存（系统侧 / .so 优化）

| 指标 | 数值 |
|------|------|
| 证据 | native_size 合计 305.89 MiB，分布极度倾斜 |
| 应用分布 | pinduoduo 172.76、gaodeditu 44.96、jingdong 33.07、kuaishou 20.47、douyin 14.60、alipay 12.56、bilibili 5.67 MiB；meituan / weibo / wechat / meituanzhongbao 均 < 0.1 MiB |
| 集中度 | pinduoduo 231 个指针（占 0.3%）承载 170.01 MiB（98.4%）；jingdong 27 个指针承载 32.61 MiB（98.6%）；gaodeditu 101 个指针承载 34.47 MiB（76.7%） |
| 零 size 指针 | pinduoduo 74,029 / 75,161（98.5%）、jingdong 79,186 / 79,687（99.4%）、kuaishou 288,197 / 289,275（99.6%） |
| 持有边 | 97% 来自 tagged_array 的 element 边 |

**问题根因**：两个独立问题。其一，off-heap 内存集中在数百个大 buffer（多为 1 MiB 量级），单应用差异达 3000 倍，说明是特定模块的缓存策略而非 VM 普遍行为；同类应用（如 meituan / weibo）几乎不占 native 内存，证明该占用可避免。其二，零 size 指针数量达 28 万（kuaishou），每个仍占 40 B 堆对象，合计 37.88 MiB 堆内存却不承载任何 off-heap 数据。

**优化方案**：
- A. 应用侧定位：针对 pinduoduo 的 231 个 / gaodeditu 的 101 个大 buffer 定位持有模块，设定容量上限与 LRU 淘汰
- B. 零 size 指针消除：native_size 为 0 的 js_native_pointer 不创建独立堆对象，指针值内联至持有者槽位（对应 37.88 MiB 堆内存）
- C. mmap 替代 malloc：> 1 MiB 的 buffer 采用 mmap 分配，释放后立即归还 OS
- D. 及时释放：增加 idle-time native pointer sweeper，不依赖 GC 触发

**预估收益**：off-heap 100–150 MiB（A + C，取决于应用配合度）；堆内 25–35 MiB（B）

---

## 10. JSObject Inline Slot 利用率（VM 改造）

| 指标 | 数值 |
|------|------|
| 证据 | 676,569 个 js_object 中 676,569 个带 Properties 边，内联区容量合计 3,151,777 slot，持有对象引用 1,630,552 slot，占用率 51.7% |
| 未持引用槽位 | 11.61 MiB（各应用 0.29–1.78 MiB） |
| 主导形态 | `(cap=4, used=0)` 为各应用最高频形态（jingdong 16,018、douyin 20,445、taobao 16,435）；wechat 特有 `(cap=5, used=4)` 45,105 个 |

**问题根因**：hclass 按 transition chain 的终态 shape 预留内联槽，`cap=4 / used=0` 形态说明存在按 4 槽固定预留、实际不放堆对象的对象族。快照仅在槽位持有堆对象时产生 InlineProperty 边，原始值（Smi、double、布尔、undefined）槽位不产生边，因此 11.61 MiB 是"未持堆对象引用"的上界，不等于全部空闲。

**优化方案**：
- A. Slack tracking 增强：当前在固定实例数后固化 slot 数，可延长为持续统计并允许配额降级
- B. 动态 inline 缩容：GC 阶段统计 hclass 族的实际最大使用槽位，对长期低利用率族缩减内联配额
- C. 可变 inline 布局：允许同一 hclass 下对象持有不同内联槽数

**预估收益**：不单独量化——快照无法区分原始值槽与空闲槽，需运行时插桩后确定

---

## 11. 字节码 / ABC 体积优化（编译器）

| 指标 | 数值 |
|------|------|
| 证据 | ConstantPool 容量 = abc IndexHeader.method_idx_size；Top13 合计 40,138,840 slot 容量对应 1,819,966 个实际 resolve 条目 |
| 单池规模 | jingdong 105 个池的 cap 均为 65,543，即 method_idx_size 已达上限 65,536 |
| method 对象 | 1,645,320 个 Method，其中 88,927 个无入边（对应未被实例化为 JSFunction 的函数声明） |

**问题根因**：abc 编译产物中 method index 按声明顺序全量编号。method_idx_size 直接决定运行时 ConstantPool 的容量，因此编译期未剔除的死方法会同时放大 abc 索引区和运行时常量池两处占用。

**优化方案**：
- A. 编译器 DCE：tree-shaking 未被引用的 MethodLiteral，缩减 method_idx_size，从源头压缩 ConstantPool 容量
- B. Index 分段：单 abc 的 method_idx 触顶 65,536 时拆分为多个 IndexHeader，避免单池按上限分配
- C. ABC 公共部分去重：HAP 打包阶段对多 abc 的公共部分（std lib、framework API stub）统一存放，减少重复方法条目

**预估收益**：本项收益体现在第 1 项 ConstantPool 与第 4 项 Method 的容量基数下降，不单独计入合计

---

## 12. Dictionary 模式对象（应用侧）

| 指标 | 数值 |
|------|------|
| 证据 | 21,268 个 tagged_dictionary = 32.19 MiB，平均 1,587 B/个；桶槽位共 757,373 个持有对象引用，其余 26.09 MiB 槽位不持堆对象引用 |
| 退化对象数 | 各应用 232–1,579 个对象处于 dictionary 模式，占 0.09%–1.10% |
| 分布 | douyin 981 个 / 2.48 MiB，weibo 1,482 个 / 2.19 MiB，jingdong 1,579 个 / 0.77 MiB |

**问题根因**：dictionary 模式对象数量占比不足 1.1%，但单个平均 1,587 B，是 fast-mode 对象的数十倍。触发原因是动态增删 key 导致 hclass 退化。哈希表的空桶为负载因子所必需，26.09 MiB 中仅超出必要负载因子的部分可压缩。

**优化方案**：
- A. 应用侧：将 dynamic-key 场景替换为 Map/Set，避免 hclass 退化路径
- B. VM 侧：dictionary 采用开放寻址 + 更高负载因子，减少桶数组容量

**预估收益**：5–10 MiB（按桶数组容量压缩 20%–40% 计）

---

## 13. ClassLiteral 常量池驻留（VM 改造 / 编译器）

| 指标 | 数值 |
|------|------|
| 证据 | 211,705 个 class_literal = 4.85 MiB；13/13 应用中 100% 由 constant_pool 的 element 边持有 |
| 分布 | douyin 39,970 个 / 0.91 MiB，weibo 34,403 个 / 0.79 MiB，jingdong 18,669 个 / 0.43 MiB |
| 关联 | cow_tagged_array 202,928 个 = 20.43 MiB，槽位填充率 89.6%（仅 2.12 MiB 槽位不持堆对象引用），其内容主体为 function_template |

**问题根因**：ClassLiteral 由常量池强引用，生命周期与 abc 加载一致。类声明数量决定其总量，与类是否被实例化无关。COW 数组本身填充充分，不存在容量浪费，其体积由承载的 FunctionTemplate 数量决定。

**优化方案**：
- A. 惰性 ClassLiteral：首次类实例化或原型访问时才从 abc 解析构造，未使用的类声明不驻留
- B. 与第 11 项联动：编译期剔除未引用的类声明，直接减少常量池条目

**预估收益**：2–4 MiB

---

## 14. LexicalEnv 余量（VM 改造）

| 指标 | 数值 |
|------|------|
| 证据 | 186,187 个 lexical_env = 11.28 MiB；不持堆对象引用的槽位合计 2.16 MiB（19.1%） |
| 分布 | douyin 28,826 个 / 1.97 MiB，jingdong 26,365 个 / 1.52 MiB，weibo 24,119 个 / 1.38 MiB |

**问题根因**：LexicalEnv 按编译期声明的变量数分配槽位。不持堆对象引用的槽位包含原始值变量与未初始化槽两类，快照不可区分。

**优化方案**：
- A. 编译器：对未被内层闭包捕获的局部变量不分配 LexicalEnv 槽，降级为栈变量
- B. VM：GC 时对无活跃闭包引用的 LexicalEnv 执行回收

**预估收益**：1–2 MiB

---

## 15. AccessorData 对象（VM 改造）

| 指标 | 数值 |
|------|------|
| 证据 | 243,266 个 accessor_data × 24 B = 5.57 MiB，全部有入边 |
| 持有方式（典型案例 kuaishou） | tagged_array element 5,140 个、js_object InlineProperty 36,405 个、Lstd/core/Object InlineProperty 2,205 个 |
| 分布 | kuaishou 43,883 个 / 1.00 MiB，douyin 33,811 个 / 0.77 MiB，weibo 32,551 个 / 0.75 MiB |

**问题根因**：每个 getter/setter 属性创建独立 AccessorData 对象（24 B = 16 B 对象头 + 8 B Getter/Setter 槽）。对于同一函数同时作为 getter 和 setter 的情况，两个槽指向同一函数但仍需两份槽位。

**优化方案**：
- A. Accessor 字段内联：将 Getter/Setter 指针直接嵌入 hclass 的 property descriptor（当前 descriptor 已占 8 B，扩展到 16 B 可容纳两个指针），消除独立 AccessorData 对象
- B. 与第 2 项联动：toJSON 闭包去重后，对应的 AccessorData 数量同步下降（若 toJSON 通过 accessor 持有）

**预估收益**：3–5 MiB

---

## 汇总

按收益排序，编号对应上文章节：

| 章节 | 维度 | 优化项 | 预估收益 MiB |
|------|------|--------|-------------|
| 1 | VM | ConstantPool 稀疏化 | 250–280 |
| 9 | System/.so | Native buffer 管控（off-heap） | 100–150 |
| 2 | VM + App | Native interop 闭包惰性绑定 | 62 |
| 5 | VM/Compiler | 模块元数据压缩 | 30–45 |
| 4 | VM/Compiler | Method 惰性分配 + 瘦身 | 30–42 |
| 9 | VM | 零 size native pointer 消除（堆内） | 25–35 |
| 8 | VM | ProfileTypeInfoCell 裁剪 | 28.5 |
| 3 | VM | TaggedArray (Elements/Properties) trim | 25–40 |
| 6 | VM | HClass 零实例回收 + 瘦身 | 20–35 |
| 7 | VM | FunctionTemplate 按需创建 | 15–25 |
| 12 | App/VM | Dictionary 对象优化 | 5–10 |
| 15 | VM | AccessorData 字段内联 | 3–5 |
| 13 | VM/Compiler | ClassLiteral 惰性驻留 | 2–4 |
| 14 | VM/Compiler | LexicalEnv 瘦身 | 1–2 |
| 10 | VM | JSObject inline slot 缩容 | 待运行时插桩量化 |
| 11 | Compiler | ABC DCE / method_idx 缩减 | 间接体现于 1、4、7、13 |

**堆内合计（取中值）**：约 520–620 MiB，相对 1,647.96 MiB 基线为 32%–38%。
**off-heap 另计**：100–150 MiB，相对 305.89 MiB 基线为 33%–49%。

> 收益重叠说明：第 11 项的编译期裁剪同时降低第 1、4、7、13 项的对象基数，其收益已计入这些项，不单独累加。第 2 项惰性绑定消除的 JSFunction 同步减少关联的 js_native_pointer（每个 40 B）和可能的 AccessorData（第 15 项）。实际叠加收益应按实施顺序递减计算，不等于各项简单求和。
>
> 第 2 项与第 6 项的「零实例」不是同一块存量：第 2 项 bucket C 指**零实例类 prototype 上的 native JSFunction 闭包**（61 MiB，对象本体）；第 6 项指**无活实例的 hclass 元数据本身**（6.81 MiB）。两者可叠加。第 2 项内部的编译期零实例类裁剪与惰性绑定互斥，取其一。

<!-- BEGIN HERMES REVIEW APPENDIX 2026-08-12 -->
## 复核意见（2026-08-12）

- **结论（P0）**：对象人口可作为机会索引；250-280 MiB ConstantPool 与 520-620 MiB 堆内合计不得发布，单项存在无边即空闲、任意回收比例和跨方案重复计数。
- **数据/源码事实**：40,102,399 用户槽减约 1,803,770 用户对象边所得 292.195 MiB 只是“无可见对象边”上界，不是 Hole；V2 还压缩 edge index。`FunctionTemplate` 仅含 Method/Module/RawProfileTypeInfo/Length（`js_function.h:732-760`）；`ProfileTypeInfoCell` 会在解释器反馈路径分配（`interpreter-inl.cpp:1046-1061`）；`AccessorData` 是 getter/setter 两槽（`accessor_data.h:83-88`）。
- **风险或反例**：正文 `top13-heap-optimization-opportunities.md:22-36,336,353` 反向采用已否决的 ConstantPool 收益；Method“无入边”与“仅由池持有”自相矛盾。Function/NAPI/模块 DCE/附属对象方案覆盖同一对象链，相加会重复；无机器码不能推出反馈对象无用途。
- **放行条件**：撤销 250-280、520-620 MiB 和未证字段裁剪；逐项给对象边下界、槽上界、源码生产/消费链、增量结构成本及与其他项集合交并；仅将独立 clean A/B 净 PSS 结果纳入路线图。
<!-- END HERMES REVIEW APPENDIX 2026-08-12 -->
