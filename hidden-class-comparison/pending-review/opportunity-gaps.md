# 其他方向机会分析（未覆盖方向缺口清单）

本文档记录**尚未被系统分析**的内存优化方向。其中 string 方向已提取为 `../feasible-proposals/04-string-optimization/`（置信度 75%），LayoutInfo 方向已升级为详细方案 `../detailed-proposals/layoutinfo-attr-packing/`。

数据来源：`team_interop/analysis/top13-memory-landscape/top13-memory-landscape.json`（13 应用合计）+ `tmp-napi-scan/*.heapsnapshot` 解析 + `evidence/top13-string-array-census.json`、`evidence/top13-layout-dedup-census.json`。

## 1. 已覆盖 vs 未覆盖（13 应用合计 heap_self ≈ 1,648 MiB）

broad_categories 分布：

| 类型 | 占用 | 覆盖状态 |
|---|---|---|
| array | 661.01 MiB（40.11%） | 部分（ConstantPool 306.3、Layout 109.25 已拆解并提取方案；Elements/Properties 空闲上界在 09） |
| native | 398.76 MiB（24.20%） | 部分（大 buffer；零 size 指针方案已放弃） |
| closure | 358.62 MiB（21.76%） | 部分（native interop 128 MiB → detailed 方案；代码槽 31–43 MiB → 07） |
| object | 83.69 MiB（5.08%） | 部分（inline slot；字面量占比未归因 → detailed-proposals/constantpool-shared-literal 前置项） |
| string | 83.03 MiB（5.04%） | 已提取 → `../feasible-proposals/04-string-optimization/`（构成已部分拆解） |
| framework | 59.42 MiB（3.61%） | 部分（模块记录 → 10） |

## 2. 本轮拆解结果（2026-08-14 复算）

### 2.1 string 83.03 MiB 构成（feeds 04）

| 维度 | 结果 |
|---|---|
| 尺寸分布 | ≤24 B：20.28 MiB；25–64 B：12.47 MiB；65–256 B：14.21 MiB；257–1K：3.44 MiB；>1K：32.63 MiB |
| 类型分布 | 全部为 `string`，**slicedstring / concatenated string 节点数为 0**——TreeString flatten 与 SlicedString 父串释放在 Top13 场景无存量可回收 |
| 持有方（引用归因，共享字符串会重复计入） | constant_pool（去重后 15.38 MiB / 685,129 个，跨 VM 共享上界）；其余为动态字符串。对象字面量 COW 方案不包含字符串共享 |
| 推论 | 04 的收益主体集中在两段：短字符串内联（≤24 B 桶 20.28 MiB，header 占比高）与大字符串驻留（>1K 桶 32.63 MiB，需业务侧归因）；中段与 flatten 子项证据不足 |

### 2.2 tagged_array 承载（修正此前的归因口径）

- 引用归因中「closure 持有 83.88 MiB 数组」实为 16 B EmptyArray **共享单例**被 500 万+ Properties/Elements 槽引用的重复计数，去重后 closure 持有的独立数组仅 ~5.5 MiB（bilibili 单应用核验）——「空数组延迟分配」的存量远小于此前估计；
- **Layout 数组去重后 735,734 个 / 109.25 MiB，与 hclass 比 0.898:1（几乎 1:1）**，已提取为 `../feasible-proposals/14-layoutinfo-attr-packing/`（Attr 槽 8 B→4 B，模型 ~24.5 MiB）；
- 其余大头（hclass Layout 之外的 js_object/js_array Elements、LinkedMap/Set 桶）维持 09 的空闲上界口径，需运行时插桩确认。

## 3. 剩余未覆盖方向

| 方向 | 占用（13 应用） | 说明 |
|---|---|---|
| JSSharedObject | 5.39 MiB（30,702 个，avg 179 B） | shared heap 的 sendable 对象，布局与共享策略未分析；量级小 |
| PrototypeHandler | 3.55 MiB（77,646 个，avg 48 B） | Proxy handler 对象，数量大单体小，未分析；量级小 |
| >1K 大字符串 | 32.63 MiB | 需按持有模块归因（业务缓存/日志），应用侧问题为主 |
| js_object 中对象字面量 backing 占比 | 未归因 | detailed-proposals/constantpool-shared-literal 的 clone/首次写专项插桩前置项 |

## 4. 结论与下一步

1. JSSharedObject / PrototypeHandler 量级 <6 MiB，低于立项门槛，暂不投入；
2. 大字符串归因建议并入 `feasible-proposals/04` 的插桩项；
3. 完成上述两项后，array/object 两类中未解释的承载已基本收敛到 09/10 的既有口径。
