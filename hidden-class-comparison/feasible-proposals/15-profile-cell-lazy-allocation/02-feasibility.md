# 可行性（Feasibility）：ProfileTypeInfoCell 按需分配

## 已确认事实

- 普通函数初始关联 `EmptyProfileTypeInfoCell`（`js_function.cpp:102-113`）；
- 父函数已有 `ProfileTypeInfo` 时，DEFINEFUNC 首次命中会创建 cell、写回 `ProfileTypeInfo[slotId]` 并关联新函数，后续同 slot 闭包复用该 cell（`interpreter/interpreter-inl.cpp:1046-1063`）；
- FunctionTemplate 路径执行相同的创建/复用协议（`js_function.cpp:1211-1223`）；
- `JSFunction::SetProfileTypeInfo` 已有 Empty→cell 转换（`js_function.cpp:1195-1205`）；
- `CELL_0/1/N` 是同 slot 复用级别，不是 `Value` 是否存在反馈的状态（`ic/profile_type_info_cell.h:47-59`）。

## 当前阻断点

现有 `SetProfileTypeInfo(func, value)` 只知道当前函数和待写入值，不知道原父 `ProfileTypeInfo + slotId`。若直接删除 DEFINEFUNC 阶段的 cell 创建，首次反馈可能只能为当前闭包建立私有 cell，把原来的一份共享记录拆成多份。

进入实现前必须证明下列定位方式之一成立：

1. 从既有元数据无歧义恢复父 profile 和 slot；或
2. 增加 GC 可见的紧凑延迟绑定记录。

第二种方式必须计入对象数、字节、barrier、local/shared heap、GC、snapshot 和 serializer 成本，并从毛收益中扣除。

## 现有改造面

- C++ 主路径：`interpreter/interpreter-inl.cpp:1046-1063`；
- DEFINEFUNC handler：`interpreter/interpreter-inl.cpp:5106,5132`；
- 生成代码：`new_object_stub_builder.cpp:1453`、`interpreter_stub-inl.h:576`、`stub_builder.cpp:12472`、`circuit_builder.cpp:1619`；
- FunctionTemplate：`js_function.cpp:1211-1223`；
- 首次反馈：`js_function.cpp:1195-1205`；
- PGO define-class：`compiler/profiler_stub_builder.cpp:129-162`、`pgo_profiler/pgo_profiler.cpp:1330-1393`。

## 风险

| 风险 | 等级 | 放行条件 |
|---|---|---|
| 同 slot 闭包被拆成私有 cell | 高 | 定位 spike 和共享/转级 DT 通过 |
| PGO define-class 丢失 `Handle` 宿主 | 高 | PGO 首触发能够解析并建立原父 slot/cell |
| 新增定位元数据抵消收益 | 高 | 实测 `32eN-M>0` |
| 首次反馈路径增加分支和分配延迟 | 中 | 微基准和业务 clean A/B |
| GC/shared heap/serializer 契约遗漏 | 中 | 全矩阵回归及对象边界压力测试 |

## 置信度

综合置信度 **65%**：事实基础 90%，机制方向 65%，具体定位表示 50%，收益置信度待插桩。当前属于“方向可行、实施前置未闭环”，不得直接删除现有分配路径。