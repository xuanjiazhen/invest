# 需求（Requirement）：ProfileTypeInfoCell 按需分配

## 背景与问题

当父函数已经有 `ProfileTypeInfo` 时，运行时在 DEFINEFUNC/FunctionTemplate 实例化阶段创建或复用 `ProfileTypeInfoCell`，与新函数是否已经产生反馈无关（`interpreter/interpreter-inl.cpp:1046-1063`、`js_function.cpp:1211-1223`）。普通函数初始只关联全局 `EmptyProfileTypeInfoCell`，因此存在将实际 cell 延迟到首次反馈或 PGO 触碰时再创建的空间。

cell 同时是同一函数定义位置的共享记录：父 `ProfileTypeInfo[slotId]` 持有一份 cell，同一位置创建的多个闭包通过各自的 `RawProfileTypeInfo` 指向它。`CELL_0/1/N` 表示这份记录被闭包复用的级别，不表示 `Value` 是否已经产生反馈。

## 目标

1. 将实际 cell 的创建从函数定义阶段推迟到首次反馈写入或 PGO 触碰；
2. 延迟创建后仍能找到并回写原父 `ProfileTypeInfo[slotId]`，保持同 slot 多闭包共享同一 cell；
3. 保持 `CELL_0→CELL_1→CELL_N`、`Value`、PGO `Handle`、GC 和 snapshot 语义；
4. 扣除延迟绑定元数据后，cell 浅层堆和设备内存净收益为正。

## 非目标

- 不裁剪 `MachineCode` 或 `Handle` 字段；字段裁槽由 `../../detailed-proposals/profile-type-info-cell-jitfree/` 独立处理；
- 不修改已冻结的 `JSFunction` 布局；
- 不用 `CELL_0` 数量代替生命周期内可避免分配数；
- 不引入执行次数阈值来规避父 slot 定位问题。

## 收益模型

设基线实际分配 cell 数为 `N`，经运行时插桩确认的可避免分配比例为 `e`，新增延迟绑定元数据总成本为 `M`：

```text
毛收益 = 32eN B
净收益 = 32eN - M B
```

快照只记录采样时仍存活的 cell，不记录“何时首次反馈”，因此 `e` 必须由 DEFINEFUNC 分配、首次反馈、PGO 触碰、同 slot 复用和进程退出未触发事件对账得到。

## 验收标准

1. 每个延迟函数都能解析到正确的父 `ProfileTypeInfo + slotId`；
2. 同 slot 多闭包按不同顺序触发反馈/PGO并穿插 GC 后，仍只建立一份共享 cell；
3. `CELL_0/1/N` 转级和全部消费者行为与基线一致；
4. 快照 cell 节点下降量与插桩确认的可避免分配量一致；
5. `32eN-M>0`，并通过同设备、同构建、同场景 clean A/B；
6. Interpreter、IC、PGO、AOT、JIT、worker、AppSpawn、serializer、snapshot 和 GC 回归通过。

## 工作量

| 任务 | 设计 | 开发 | 测试 | 小计 |
|---|---:|---:|---:|---:|
| 生命周期插桩与 `e` 采集 | 1 | 1 | 5 | 7 |
| 父 profile/slot 定位表示 spike 与 ADR | 3 | 5 | 4 | 12 |
| 7 条路径、首触发和共享关系实现 | 2 | 8 | 6 | 16 |
| PGO/shared heap/共享转级实现 | 1 | 4 | 4 | 9 |
| **合计** | **7** | **18** | **19** | **44 人日** |

前 19 人日用于插桩和定位 spike；正确性或净收益门槛未通过时，不进入后续 25 人日实现。