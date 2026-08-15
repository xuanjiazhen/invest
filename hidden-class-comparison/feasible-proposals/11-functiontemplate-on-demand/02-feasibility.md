# 可行性（Feasibility）：FunctionTemplate 按需创建

## 证据
- 布局：js_function.h:732-758（Method/Module/RawProfileTypeInfo/Length，40B）；
- 存量：954,059 个 = 36.39 MiB（top13-memory-node-names.csv）。

## 技术路径
NewJSFunction 首次创建时再建 template。

## 风险与阻碍
- 15-25 MiB 按未实例化占比 40-70% 估算，实际需运行时确认；
- Method 的 88,927 无入边与「仅由池持有」自相矛盾，不能作为裁剪比例依据。

## 置信度
60%（事实 90% / 机制 55% / 收益取决于未实例化占比）。