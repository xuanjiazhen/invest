# 特性（Feature）：字符串优化

## 功能描述
短字符串内联存储、未 intern 字符串去重、TreeString 及时 flatten、SlicedString 不钉住大父串。

## 影响范围
- VM 字符串分配路径（ecma_string / line_string / tree_string / sliced_string）；
- 字符串表（ecma_string_table）。

## 兼容性
字符串语义不变（===、length、编码、intern 去重行为一致）。

## 验证计划
1. 拆解 string 83 MiB 构成；
2. 按子方向做原型 + 性能/内存对照；
3. GC/serializer/AOT 回归。