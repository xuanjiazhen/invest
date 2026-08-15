# 需人工判断方案（置信度 <60%，或收益完全未定）

本文仅保留**置信度 <60%** 的方案。已定去向：

- Native interop 惰性绑定 → `../detailed-proposals/native-interop-lazy-binding/`
- FunctionTemplate 按需创建 → `../feasible-proposals/11-functiontemplate-on-demand/`
- JSFunction code-slot 移除 / AccessorData 内联 / TaggedArray trim / 模块元数据压缩 / ClassLiteral 惰性驻留 / method_idx 缩减 → 人工否决，见 `rejected.md` §8–13

## 1. LexicalEnv 瘦身（编译器侧，~55%）

- 出处：`top13-heap-optimization-opportunities.md:295-309`
- 存量：186,187 个 lexical_env，不持堆对象引用槽 2.16 MiB（19.1%）。
- 需补证据：快照不可区分原始值变量与未初始化槽；需编译器侧证明未被闭包捕获的局部变量可降级栈变量。

## 2. JSObject inline slot 缩容（~50%）

- 出处：`top13-heap-optimization-opportunities.md:221-236`
- 现状：不单独量化——快照无法区分原始值槽与空闲槽（11.61 MiB 是「未持引用」上界）。slack tracking 机制 ArkVM 已有（`--enable-inline-property-optimization` 附带启用，`js_runtime_options.cpp:232`；`VisitTransitionAndUpdateObjSize`，`js_hclass-inl.h:358`）。
- 放行条件：先确认产品档位默认值与 `(cap=4, used=0)` 高频形态成因（未开启 / 未固化 / 原始值槽），再决定是否立项。

## 3. Dictionary 模式对象优化（VM 侧开放寻址）

- 出处：`top13-heap-optimization-opportunities.md:259-273`
- 存量：21,268 个 tagged_dictionary = 32.19 MiB；退化触发是动态增删 key。
- 说明：应用侧「dynamic-key → Map/Set」路径已并入 `../feasible-proposals/02-app-side-consolidated/` A4；本节仅保留 VM 侧「开放寻址 + 更高负载因子」方向，收益 5–10 MiB 是桶压缩估算。
- 放行条件：VM 侧需哈希表负载因子/探测链性能实测。