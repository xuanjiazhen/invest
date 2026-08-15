# 架构决策记录（ADR）：FunctionTemplate 按需创建

## 状态
提议。

## 背景
template 数量与函数声明数同阶，未实例化函数也分配。

## 决策
首次 NewJSFunction 时创建 template；COW 数组持有链按需填充。

## 权衡
| 方案 | 优点 | 代价 |
|---|---|---|
| 按需创建（选） | 降 template 基数 | 首次创建延迟 |
| 保持现状 | 无风险 | 36.39 MiB 常驻 |

## 影响
jsnapi 创建路径、COW 数组、常量池持有链。