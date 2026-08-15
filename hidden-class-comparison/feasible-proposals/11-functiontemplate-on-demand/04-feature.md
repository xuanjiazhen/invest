# 特性（Feature）：FunctionTemplate 按需创建

## 功能描述
首次 NewJSFunction 时创建 template，未实例化函数声明不分配。

## 影响范围
FunctionTemplate 创建路径、cow_tagged_array 持有链。

## 兼容性
函数创建语义不变；首次创建增加一次分配延迟。

## 验证计划
1. 插桩实例化率；
2. 按需创建后对比 COW 数组持有链；
3. Top13 快照对比 template 数量。