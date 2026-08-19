# 特性（Feature）：LayoutInfo 共享

## 1. 改动点

| 位置 | 改动 |
|---|---|
| `js_hclass.cpp:440,474` | proto/extensible transition 删除 `CopyLayoutInfo`，直接继承父数组 |
| `js_hclass.cpp:778-783` | attr 更新 transition：先尝试族内一致化（attr 位族内可统一时）否则 COW 拷贝 |
| `layout_info-inl.h` 五个就地变更者 | 统一走 `EnsureSoleOwnerOrCopy()` 前置（独占检查 → 必要时整组拷贝）；`SetSortedIndex` 仅存在于私有追加路径，追加前已保证独占 |
| 所有权标记 | hclass BitField 备用位增设 layout-owner 位（或数组内 owner 回指），分支 transition 时移交/失效 |
| 跨 context intern 表 | Runtime 级 `LayoutInfoInternTable`：key = (有序 keys, attrs) 内容哈希；新建前查表；命中且为不可变值则复用；任何变更经 COW 后重新登记 |
| slack 追加（可选，B 项） | `AddKey` 在独占 + 容量富余时原地写入，数组 length 不变、hclass NumberOfProps +1 |
| 工具 | serializer/rawheap/heap_snapshot：共享数组多入边的归因输出；PGO dump 按 hclass 视图（依赖 14-B 的 IsPGODumped 堆外化） |

## 2. 语义保持

- 属性查找结果、枚举顺序、TrackType 演化终态、PGO 采集内容不变；
- 共享仅消除「相同内容的第二份及以后拷贝」，任何写入仍保证该 hclass 视图即时可见（COW/一致化保证）。

## 3. 验证

- 正确性：transition 全矩阵（加属性/换原型/freeze/attr 更新/TrackType 演化/字典往返）、多 context/worker 同 shape、枚举序、AOT/PGO 回归；
- 并发：TSAN 下多线程 hclass 变更 + 共享数组读；GC 全矩阵（共享数组的标记/移动/回收——无 owner 引用后回收）；
- 内存：Top13 双版本快照——Layout 数组数/字节对照等价组模型；PSS 不回退；
- 插桩核验：dump 侧全内容哈希（attr 并入）重算等价组 → 真实收益；transition 拷贝点分类计数归零验证（proto/extensible）。

## 4. 关联

- 依赖：14-B 的 IsPGODumped 堆外化（标志位出数组）为共享的前置之一；
- 排序约束：**先 16（共享）后 14（编码压缩）**，14 收益基数随 16 缩水（23.17 → ~6 MiB），合并排期避免重复施工；
- 数据与脚本：`evidence/top13-layout-sharing-model.json`、`scripts/layout_family_sharing_model.py`。
