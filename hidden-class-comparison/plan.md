针对鸿蒙场景JSHideClass的对象布局进行分析并提供一份现状分析和潜在优化方向的报告
1、首先包含鸿蒙Arkts VM 动态当前 JSHideClass的布局情况，大小占比，先整体介绍，然后展开介绍每个字段的产生和消费用途
2、提供各个竞品和ArkTSVM实现效果整体对比情况，子章节逐个展开分析介绍竞品大的字段用途，以及每个字段产生和消费用途，以及与ArkTSVM差异部分的处理做法。
3、结合上述内容分析，给出可能的优化方案，每个优化方案单独介绍，包括：1、预估效果2、改动工作量 3、影响范围，兼容性，对已有的功能稳定性影响等等 

当前任务的主要目的是分析arkvm底层实现在应用运行时内存上额优化空间。jhclass只是其中一个潜在的方向。请不要局限于该方向，整体看看其他是否还有空间，尤其是在低内存设备上的空间。

当前已有大模型进行了部分分析，但它的结论可能是错的。基于事实内容，重新进行分析。


上下文：D:\docker\invest\hidden-class-comparison\CONTEXT.md

分析实际应用的内存快照发现：
排名top的对象内存有如下几类：
Function
hclass
js_object
js_native_pointer
string
method
source_text_module_record
js_array
profile_type_info_cell_0
js_map
js_set

请按照优先级从上到下逐个分析一下各类对象的内存布局组成，单独输入一份文件，结合具体代码进行举例说明。 并且发现在内存快照中出现很多InlineProperty ，一并解释该字段含义。

<!-- BEGIN HERMES REVIEW APPENDIX 2026-08-12 -->
## 复核意见（2026-08-12）

- **结论（P1）**：本文是原始任务说明，不是可验收计划；对象清单可保留，但缺版本矩阵、统计定义、输出物和逐项放行门槛。
- **数据/源码事实**：`plan.md:13-27` 只列对象与“逐个分析”要求，且 `:11` 引用已陈旧 CONTEXT。源码实际存在 `SourceTextModule`（`module/js_module_source_text.h:67-97,342-367`）和 `ProfileTypeInfoCell`（`ic/profile_type_info_cell.h:30-59`），必须做快照标签到 JSType/class 的映射。
- **风险或反例**：未区分 translator V1/V2 会把“无对象边”误作空槽；未定义对象本体、附属对象、retained、毛/净收益和集合去重，会让 ConstantPool 等已否决收益进入总账。
- **放行条件**：补输入哈希、translator V1/V2、双仓 commit、64-bit/build flags、逐类型源码证据、复现脚本、输出文件和 P0/P1 门禁；收益必须区分对象边下界、无对象边上界、真实结构成本与 clean A/B 净值。
<!-- END HERMES REVIEW APPENDIX 2026-08-12 -->
