# 特性说明：ProfileTypeInfoCell 按需分配

## 系统位置

```text
父 ProfileTypeInfo[slotId] ──拥有──> 共享 cell
                                      ↑
同一 DEFINEFUNC 位置创建的闭包 ──────┘
```

父表的一项只拥有一份共享记录，多个闭包只是引用者。延迟创建必须恢复并更新原父表项，不能为各闭包分别创建记录。

## 触发流程候选

```text
DEFINEFUNC
  └─ 保持 Empty，并保存/恢复父 profile + slot 的定位能力
       ├─ 首次 IC 反馈写入 ─┐
       └─ 首次 PGO 触碰 ───┴─> 原子建立父 slot 的 cell
                                  ├─ 回写父 ProfileTypeInfo[slotId]
                                  ├─ 关联相关闭包
                                  └─ 写入 Value 或 Handle
```

## 必须保持的协议

- `Value` 的解释器、IC、AOT、PGO 和 JIT 消费；
- PGO define-class 对 `Handle` 的弱引用读写；
- `CELL_0→CELL_1→CELL_N` 的复用分级；
- Empty 哨兵、local/shared heap、barrier 和 GC visitor；
- snapshot、serializer、AppSpawn、hprof/rawheap/debugger；
- JIT 候选遇 Empty 时仍按无反馈处理。

## 构建与验证

原型必须先在全能力构建验证 Interpreter/PGO/AOT/JIT，再覆盖 JIT-free、worker、AppSpawn 和 shared heap。正式收益使用同设备、同构建、同场景 clean A/B，分别报告 cell shallow、Region used/committed、RSS/PSS 和性能。