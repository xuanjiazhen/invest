# 可行性（Feasibility）：字符串优化

## 证据
- 快照：string 83.03 MiB（13 应用合计）；空名字节点 65.09 MiB 经解析确认为 string（bilibili 39,173/39,174 为空 name string）；
- 源码：LineEcmaString（compressed/UTF8 位，line_string.h DATA_OFFSET=BaseString::SIZE）、TreeEcmaString、SlicedEcmaString、CachedExternalEcmaString；GetOrInternString（ecma_string_table.h）。

## 技术路径
短字符串内联存储 / intern 策略补全 / TreeString flatten 时机 / SlicedString 弱持有父串。

## 风险与阻碍
- 收益依赖构成拆解（长度分布/类型占比/intern 命中率），当前未量化；
- 字符串为热路径对象，内联/flatten 需性能回归。

## 置信度
75%（事实 90% / 机制 70% / 收益待拆解构成）。