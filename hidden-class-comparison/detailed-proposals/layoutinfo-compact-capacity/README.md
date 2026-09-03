# LayoutInfo 确定性容量策略：方案摘要

本方案研究 LayoutInfo 的 capacity 策略选择，不做 LayoutInfo 内容共享、canonical table、immutable state 或 COW。

策略按证据强度分层：

1. **最终布局已知**：使用精确 capacity；
2. **存在版本化外部布局画像**：使用预测属性数加受控余量；
3. **无可靠信息**：继续使用当前 GROW。

不能因为快照显示存在空洞，就对所有创建调用直接使用精确属性数。精确分配可能把一次追加变成 LayoutInfo copy/extend，增加分配、复制、GC 和延迟成本。

## 物理模型

```text
self_size = 16 + 16 × capacity
```

当前默认 GROW 在未触及上限时近似：

```text
capacity = properties + 4
```

每个额外 capacity 为 16 B，因此默认 `N+4` 相比 `N` 多 64 B。

## 证据和收益上界

| 样本 | capacity 压到有效属性数的结构上界 |
|---|---:|
| 快手前台 | 3,348,784 B（3.19 MiB） |
| 快手后台 full-GC 后 | 3,106,544 B（2.96 MiB） |
| TOP13 独立快照合计 | 20,662,928 B（19.71 MiB） |

这些是结构 slack 上界，不是创建路径归因，也不是 RSS/PSS 实测。

## 策略选择

```text
finality proven        -> KEEP(final_count)
external profile valid -> predicted_count + reserve
otherwise              -> existing GROW
```

外部画像必须绑定 runtime revision、ABI、bundle、class identity、属性顺序和配置。发生原型/继承/descriptor/representation/属性顺序变化、profile mismatch 或预测容量不足时立即失效并回退 GROW。

## 竞品启示

V8 公开采用 in-object slack tracking：先依据编译/构造信息保留余量，用 construction counter 观察 map transition tree 的实际使用情况，再收缩后续对象的 instance size。ArkVM 已有相近的 HClass/object-size tracking：`--enable-inline-property-optimization` 启用 slack tracking，construction counter 在若干次对象构造后遍历 transition tree 并更新 object size。

这可以作为 LayoutInfo 策略的设计参考，但不能直接复用，因为 HClass object-size tracking 与 LayoutInfo backing capacity 是不同对象、不同生命周期和不同写入契约。

## 当前状态

已完成新方案文档、源码证据整理、快手/TOP13 统计复算和竞品资料核对。尚未完成创建路径插桩、C++ 编译、运行时测试或 clean A/B。

## 归档结构

| 文件 | 内容 |
|---|---|
| `01-背景.md` | LayoutInfo 物理格式和当前分配策略 |
| `02-需求.md` | 目标、范围、策略约束和验收 |
| `03-方案设计.md` | 分层容量策略、外部画像、fallback 和验证 |
| `04-源码与数据证据.md` | 源码与快照证据 |
| `05-收益数据.md` | 结构上界和各样本数据 |
| `06-复现说明.md` | 复现方法 |
| `07-运行时分类插桩.md` | 运行时数据采集 |
| `08-外部画像与策略选择.md` | 画像匹配和 capacity 选择算法 |
