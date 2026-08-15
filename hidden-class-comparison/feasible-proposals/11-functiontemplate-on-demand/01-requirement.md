# 需求（Requirement）：FunctionTemplate 按需创建


## 背景与问题
FunctionTemplate 954,059 个 = 36.39 MiB（40B，仅 Method/Module/RawProfileTypeInfo/Length 四字段），100% 由 cow_tagged_array 的 element 边持有。未实例化的函数声明也分配 template。

## 目标
仅在首次 NewJSFunction 时创建 FunctionTemplate，降低未实例化函数的 template 基数。

## 非目标
- 不改 COW 数组持有链语义。

## 验收标准
1. 插桩 NewJSFunction 实例化率确认未实例化占比；
2. 按需创建后 COW 数组持有链对比。

## 插桩验证

见 `05-插桩patch.md`：创建侧 `DefineFunctionTemplate`（`literal_data_extractor.cpp:281/283`）+ 消费侧 `CreateJSFunctionFromTemplate` 全调用点（`class_info_extractor.cpp:422-553`）对账，输出 `neverInstantiated%` 与 `neverInstantiatedBytes`（×40 B）；原型后复测 template 节点数下降即为实测收益。

## 关联与依赖
- 与方案 13（method_idx 缩减）联动（函数声明总数下降直接降 template 基数）。