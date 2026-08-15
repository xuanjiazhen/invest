# rawheap 快照解析与对象布局收益量化方法

## 0. 适用范围

本文归档 ArkVM `.rawheap` 快照的解析链路与对象布局收益的量化方法，供后续同类分析直接复用。

材料来源：`hidden-class-comparison` 目录下 `jshclass-layout-review.md`、早期 JSFunction 代码槽方案（已否决）两处取数工作，输入为 `D:\docker\plan\top13` 的 13 个 `.rawheap`。

本文只记录方法与可直接核验的事实依据，不重复两份方案的结论数据。

---

## 1. 工具链

### 1.1 转换器选型

| 项 | 值 |
|---|---|
| 可用二进制 | `D:\DevEcoStudio6.1\sdk\default\openharmony\toolchains\rawheap_translator.exe` |
| 调用形式 | `rawheap_translator.exe <in.rawheap> <out.heapsnapshot>`，两个位置参数，无 flag |
| 输出 | Chrome DevTools `.heapsnapshot` JSON |

仓库内的 `prebuilts/js_rawheap_translator/windows/js_rawheap_translator.exe` 对这批 rawheap 报 `rawheap magic mismatch`，不能使用。转换器与 rawheap 之间存在版本约束，比较逻辑在 `dfx/hprof/rawheap_translate/utils.h:125-150` 的 `Version::operator<`，转换前应确认 SDK 版本与快照采集版本匹配。

### 1.2 输入组织

Top13 的 rawheap 位于按应用命名的子目录中（`alipay_203MB/` 等），根目录下用 `*.rawheap` 通配返回空。递归查找：

```bash
find /d/docker/plan/top13 -name "*.rawheap"
```

### 1.3 中间产物管理

13 个 `.heapsnapshot` 合计约 2.1 GB。它们是可重新生成的中间产物，分析完成后应删除，只保留脚本与统计结果。

---

## 2. 解析 heapsnapshot 的数据结构

`.heapsnapshot` 是扁平数组格式，节点与边都按固定 stride 编码：

```python
m  = d['snapshot']['meta']
nf = m['node_fields']; st = len(nf); fi = {n: i for i, n in enumerate(nf)}
ef = m['edge_fields']; es = len(ef); efi = {n: i for i, n in enumerate(ef)}
et = m['edge_types'][0]
nodes, edges, strs = d['nodes'], d['edges'], d['strings']
n = len(nodes) // st
```

边不按节点分组存储，需先累加 `edge_count` 建立每个节点的边起始索引：

```python
starts = [0]*(n+1); a = 0
for i in range(n):
    starts[i] = a; a += nodes[i*st + fi['edge_count']]
```

字段边与元素边必须区分：字段边的 `name_or_index` 是字符串下标，元素边是整数下标。遍历字段边时跳过 `element` 类型，否则会把数组下标当成字段名：

```python
def named(i):
    ec = nodes[i*st+fi['edge_count']]; b = starts[i]*es
    for k in range(ec):
        o = b + k*es
        if et[edges[o+efi['type']]] == 'element':
            continue
        yield strs[edges[o+efi['name_or_index']]], edges[o+efi['to_node']]//st
```

`to_node` 存的是**字节偏移**而非节点序号，必须除以 stride。

大快照的 JSON 可能含非法字符，用 `errors='replace'` 与 `strict=False` 读取更稳：

```python
d = json.loads(open(path, encoding='utf-8', errors='replace').read(), strict=False)
```

---

## 3. 三条决定结论正确性的准则

以下三条不是编码技巧，是方法本身的成立条件。违反任何一条都会得到量级错误的结果。

### 3.1 缺席的边不代表缺席的槽

`RawHeapTranslateV2::GetNextEdgeTo`（`rawheap_translate.cpp:1822-1846`）在读到 `ZERO_VALUE` 标记时返回 `nullptr`：

```cpp
uint8_t tag = *reinterpret_cast<uint8_t *>(mem_ + memPos_++);
if ((tag & ZERO_VALUE) == ZERO_VALUE) {
    return nullptr;
}
```

`ZERO_VALUE` 定义于 `rawheap_translate/common.h:114`。同理 `INTL_VALUE`、`DOUB_VALUE` 也只推进偏移不产生边。

**后果**：一个槽只有在持有活引用时才产生字段边。JIT 关闭时 `MachineCode` / `BaselineCode` 恒为 `Undefined`，几乎不产生任何边——`bilibili` 快照中带这两类边的节点仅 14 个，且全部是 `js_bound_function`。按实例边计数会把这两个槽的持有者数量低估到接近零。

**规避**：任何"某类对象有多少个"的统计都不能用"该对象是否出现某条字段边"作判据。

### 3.2 类型是 HClass 的属性，不是实例的属性

`JSType` 由 HClass 的 `ObjectType` 位域携带，实例尺寸由 HClass 的 `ObjectSize` 决定。因此布局归属必须**先在 HClass 上判定，再套用到该 HClass 的全部实例**：

1. 按 `hclass` 边把所有实例分桶；
2. 若某 HClass 的**任一**实例曾产生过目标字段边，则该 HClass 属于目标类族；
3. 该 HClass 的**全部**实例都拥有对应布局。

这一步同时化解了 §3.1 的问题：单个实例的槽可能全为 `Undefined`，但同一 HClass 下只要有一个实例的槽非空，整个桶的归属即确定。

**验证**：按此法统计的完整尾部 `JSFunction` 实例数与 `team_interop/analysis/top13-jit-off/top13-jit-off-estimates.csv` 的 `jsfunction_full_layout_count` 在 13 个应用上逐项一致。

### 3.3 同名字段不等于同一个类

`FunctionTemplate`（`js_function.h:732-758`）由 `TaggedObject` 直接派生，40 B，却含有与 `JSFunction` 同名的 `Method` / `Module` / `RawProfileTypeInfo` 字段。按字段名筛选会把它误计入函数对象，每应用约 2.2 万个实例。

**规避**：按字段名做类族筛选时，必须显式排除同名但不同基类的对象。快照中 `function_template` 是独立的节点名，可直接按名字排除。

---

## 4. 两类量化任务的具体方法

### 4.1 尺寸档位反解

`self_size` = 具体类的 `SIZE` + 8 × 内联槽数。未定义的内联槽不产生 `InlineProperty` 边，因此不能直接用 `self_size` 判档位。

减去 8 × `InlineProperty` 边数可还原基类尺寸，该值与槽是否为 `Undefined` 无关：

```python
ninline = sum(1 for x in names if x == 'InlineProperty')
base = self_size - 8 * ninline
```

对照的档位常量（`ENABLE_MEMORY_OPTIMIZATION` = 1，无 `WorkNodePointer`）：

| 类 | SIZE |
|---|---:|
| `JSObject` | 32 B |
| `JSFunctionBase` | 56 B |
| `JSApiFunction` | 80 B |
| `JSFunction` | 112 B |

该方法有残余误差：内联槽本身若为 `Undefined` 同样不产生边，因此 `ninline` 是下界，反解出的 `base` 偏大。它适合确认主峰位置，不适合精确分类；精确分类走 §3.2 的 HClass 粒度。

### 4.2 从源码约束推导快照判据

需要在快照里区分"某个宏会影响的对象"与"不受影响的对象"时，直接的类型标记往往不存在，需要从源码找一个**必然伴随**的可观察特征。

以区分 NAPI 创建的函数为例，推导链条是：

1. 宏 `ENABLE_API_FUNCTION_OPTIMIZATION` 的 8 个生效点全部位于 `ecmascript/napi/`；
2. 8 个生效点之后**无一例外**紧跟 `JSFunction::SetFunctionExtraInfo`；
3. 该函数把一个 `JSNativePointer` 写到 `HASH_OFFSET`，若该位已被哈希占用则改写入 `TaggedArray` 的 `FUNCTION_EXTRA_INDEX` 槽（`js_function.cpp:1110-1149`）；
4. 生产代码中调用它的只有 `ecmascript/napi/jsnapi_expo.cpp`。

得到判据：**`HashField` 直接指向 `js_native_pointer`，或经 `tagged_array` / `cow_tagged_array` 元素指向 `js_native_pointer`**。

```python
def is_napi_hash(t):
    if nm(t) == 'js_native_pointer':
        return True
    if nm(t) in ('tagged_array', 'cow_tagged_array'):
        return any(nm(x) == 'js_native_pointer' for x in elems(t))
    return False
```

该判据的关键性质是它同时正确排除了内建函数：`Object.keys` 等同样是原生入口，但由 `builtins.cpp` 经 `CreateFunctionClass` 创建，不调用 `SetFunctionExtraInfo`，因而不带此特征——与宏的实际作用面一致。

**代理判据不可用**：以"是否存在 `ProtoOrHClass` 边"作代理判据，只能覆盖类构造函数一类创建路径，遗漏三个 `FunctionRef::New` / `NewConcurrent` 站点创建的普通 NAPI 函数，量级偏差约 60 倍（0.46% 对 27.92%）。判据必须覆盖目标集合的全部创建路径，覆盖性由源码调用点清单确认，不能由抽样验证。

### 4.3 传递闭包与上下界

统计"某个子集有多大"时，若种子集合只能覆盖有直接证据的部分，需要判断它是下界还是确值。

以 shared 堆 HClass 为例：

- **种子**：至少有一个存活 shared JSType 实例的 HClass；
- **闭包**：`JSHClass::Clone` / `CloneWithNewSizeAndType` 在源 HClass 位于 shared 堆时把新 HClass 也分配在 shared 堆（`js_hclass.cpp:234-238, 256-260`），而 transition 由克隆构建，因此从 shared 种子沿 `Transitions` / `Parent` 双向可达的 HClass 全部是 shared。

沿这两类边做双向 BFS 得到闭包。7 个采样应用中闭包与种子完全相等，原因是 `shared_object_factory.cpp:140,159` 的 `SetExtensible(false)` 使 shared 对象不产生属性添加 transition。**闭包等于种子这一事实把下界升格为确值**，这是结论可用的前提。

### 4.4 离群值处理

逐应用统计出现单个应用显著偏离时，需要同时给出含与不含该应用的两个口径，并说明其绝对量对合计的影响权重。

Top13 的 NAPI 占比中 `kuaishou` 为 68.18%，其余 12 个应用在 9.14%–35.40%。其绝对值占 Top13 NAPI 总量的 33.1%——单个应用即可左右合计口径，因此两个口径都必须列出，不能只报合计。

---

## 5. 交叉验证

任何统计结论至少要有一条独立路径复核：

| 验证方式 | 应用实例 |
|---|---|
| 与既有 CSV 逐项比对 | HClass 粒度统计的完整尾部实例数与 `top13-jit-off-estimates.csv` 的 `jsfunction_full_layout_count` 在 13 个应用上逐项一致 |
| 理论 SIZE 与实测 `self_size` 对账 | 差值应能被内联槽数完全解释，否则说明档位判断有误 |
| 两个独立脚本互校 | 宽松匹配（`shared_` 前缀）与严格匹配（`js_shared_` 前缀）的 shared HClass 统计在 douyin 上相差 1 个节点，差异定位到具体节点后取严格版 |
| 上下界收敛 | 种子与闭包相等，下界升格为确值（§4.3） |

---

## 6. 归档清单

分析结束后应保留与应删除的内容：

| 类别 | 处置 |
|---|---|
| 统计脚本 | 保留于 `scripts/`，脚本 docstring 中写明方法依据的源码位置 |
| 统计结果（数值） | 写入方案文档 |
| `.heapsnapshot` 中间产物 | 删除，可由 rawheap 重新生成 |
| `.rawheap` 源文件 | 保留，删除中间产物前须确认源文件完好 |

方案文档中，取数方法与逐应用数据应置于附录，正文只保留结论与关键判据，避免方法叙述淹没结论。

---

## 7. 脚本清单

`scripts/` 下的脚本对应本文各节方法，每个脚本的 docstring 记录其方法依据的源码位置。全部接受一个或多个 `.heapsnapshot` 路径作为位置参数，逐应用输出统计行并在末尾输出 `---JSON---` 分隔的机器可读结果。

| 脚本 | 用途 | 对应章节 |
|---|---|---|
| `peek.py` | 打印快照的 `node_fields` / `edge_fields` / 类型表与节点名频次，用于确认新快照的字段布局 | §2 |
| `layout_resolve.py` | 按 `self_size - 8 × InlineProperty` 反解基类尺寸，输出档位直方图 | §4.1 |
| `hclass_census.py` | HClass 粒度的函数对象普查，区分完整尾部与 `JSApiFunction` 档位 | §3.2 |
| `top13_census.py` | Top13 完整尾部实例统计，含 `PROXY` / `API` / `AMBIG` 分类 | §3.2、§3.3 |
| `napi_census.py` | 按 `HashField` → `js_native_pointer` 判据切分 NAPI 创建的函数 | §4.2 |
| `shared_hclass_census.py` | 实例种子法统计 shared 堆 HClass | §4.3 |
| `shared_closure.py` | 沿 `Transitions` / `Parent` 双向 BFS 求传递闭包，给出上下界 | §4.3 |

---

## 8. 事实依据索引

本文引用的全部源码位置，均可在 `arkcompiler/ets_runtime` 直接核验：

| 事实 | 位置 |
|---|---|
| 零值标记不产生边 | `dfx/hprof/rawheap_translate/rawheap_translate.cpp:1822-1846` |
| `ZERO_VALUE` 定义 | `dfx/hprof/rawheap_translate/common.h:114` |
| 转换器版本比较 | `dfx/hprof/rawheap_translate/utils.h:125-150` |
| `JSFunction` 布局与 SIZE | `js_function.h:185-256`、`js_function.h:480-501` |
| `FunctionTemplate` 布局 | `js_function.h:732-758` |
| `SetFunctionExtraInfo` | `js_function.cpp:1110-1149` |
| 宏的 8 个生效点 | `napi/jsnapi_class_creation_helper.cpp:156,181`、`napi/jsnapi_expo.cpp:3828,3857,3886,3991,4027,4095` |
| 内建函数创建路径 | `builtins.cpp:287-289, 744-746` |
| HClass 克隆的堆归属 | `js_hclass.cpp:234-238, 256-260` |
| shared 对象不可扩展 | `shared_object_factory.cpp:140,159` |
| 内联槽容量 | `js_hclass.h:418` |
| `JSHClass` 尺寸 | `js_hclass.h:2211-2223`，`DEFINE_ALIGN_SIZE(LAST_OFFSET)` → 88 B |

<!-- BEGIN HERMES REVIEW APPENDIX 2026-08-12 -->
## 复核意见（2026-08-12）

- **结论（P0）**：本文若限定到已验证的 V2 样本，若干原则可复用；当前把 V2 边语义泛化为所有 rawheap，且用 InlineProperty/element 边反推物理槽，方法范围不成立。
- **数据/源码事实**：V1 `BuildArrayEdges` 对每个物理槽递增 index（`rawheap_translate.cpp:949-968`）；V2 遇到 ZERO/INTL/DOUB 返回空且仅在对象目标存在时递增 index（`:1764-1773,1822-1845`）。因此 V2 element 名称是已发出对象边的压缩序号；InlineProperty 边也只覆盖对象引用。当前 13 份统计的 4,049 pools、40,138,840 物理槽和 1,819,966 element 边不能推出同数 resolved 槽或 highest-used index。
- **风险或反例**：`self_size - 8 × InlineProperty` 会把 Smi/double/boolean/Undefined 当空槽；“闭包未扩张”只对指定样本与判据成立；输入缺哈希和 translator binary，无法防同名文件或协议版本漂移。
- **放行条件**：先识别协议版本并分写 V1/V2 算法；槽统计只报告对象边下界与无对象边上界，highest-used/value kind 由 VM 插桩闭合；归档输入哈希、translator/源码 commit、命令与 fixture 断言。
<!-- END HERMES REVIEW APPENDIX 2026-08-12 -->
