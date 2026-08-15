# ArkTS VM ConstantPool 完整解析（面向编译器开发者）

> 本文面向「有编译器/字节码经验、但对 VM 内部不熟」的读者，讲清楚 ConstantPool 从字节码到运行时堆对象的完整链路，作为后续优化分析的参考。

## 1. 一句话总结

ConstantPool 是 **abc 字节码与运行时堆对象之间的「常量索引表」**：字节码指令用整数索引（`method_id` / `string_id` / `type_id` / `field_id`）引用常量，运行时用**同一个索引**在 ConstantPool 数组里取出真正的堆对象（Method、ClassLiteral、字符串等）。

```
abc 字节码                          ConstantPool（运行时堆对象数组）
┌─────────────────────┐            ┌──────────────────────────────┐
│ lda.str   3         │──index 3──▶│ [0]  Hole                    │
│ newobj    7         │──index 7──▶│ [1]  Method("foo")           │
│ call.range 9        │──index 9──▶│ [2]  ClassLiteral            │
│ ldobj     5         │──index 5──▶│ [3]  EcmaString("hello")     │
└─────────────────────┘            │ ...  Hole ...                │
                                   │ [N-1] Hole                    │
                                   └──────────────────────────────┘
```

---

## 2. 字节码视角（编译器开发者熟悉的部分）

### 2.1 指令如何引用常量

ArkTS 字节码指令的操作数直接就是 ConstantPool 槽位索引（`isa.yaml`）：

| 指令 | 操作数 | 对应常量 | 取出的堆对象 |
|---|---|---|---|
| `lda.str string_id` | string_id | 字符串字面量 | `EcmaString` |
| `newobj v, type_id` | type_id | 类字面量 | `ClassLiteral` |
| `ldobj v, field_id` | field_id | 字段引用 | 字段描述符 |
| `call.range method_id, v` | method_id | 方法引用 | `Method` |

**关键点**：操作数是编译期固定的整数，运行时直接用它对 ConstantPool 数组寻址（`GetObjectFromCache(thread, index)`）。

### 2.2 IndexHeader 与 method_idx_size

abc 文件有一个索引区（index section），每个 `IndexHeader` 定义各索引空间的大小：

```cpp
// libpandafile/file.h:81-92
struct IndexHeader {
    uint32_t start, end;              // 索引空间范围
    uint32_t class_idx_size;          // 类索引条目数
    uint32_t class_idx_off;
    uint32_t method_idx_size;         // ← 方法索引条目数（直接决定 ConstantPool 容量）
    uint32_t method_idx_off;
    uint32_t field_idx_size;
    uint32_t field_idx_off;
    uint32_t proto_idx_size;
    uint32_t proto_idx_off;
};
```

`method_idx_size` 的上限是 **65,536**（`file_format.md`）。运行时 `NewConstantPool` 用它作为 ConstantPool 的用户区容量。

### 2.3 method_idx_size 为什么「虚高」

- abc 打包时，method 按**声明顺序全量编号**——未引用的死方法同样占编号空间；
- 因此 `method_idx_size` 反映了「声明的方法总数」，不是「实际存活/被引用的方法数」；
- 极端案例：**jingdong 105 个 ConstantPool 的 cap 全部触顶 65,543**（method_idx_size = 65,536），而实际填充率仅 **0.04%–2.62%**（单池 524 KB 只 resolve 几十到一千多条）。

**结论**：ConstantPool 的容量浪费是**编译产物层面的确定性浪费**（`method_idx_size` 虚高），不是运行时随机行为。

---

## 3. 运行时视角（VM 侧）

### 3.1 ConstantPool 是变长 TaggedArray

ConstantPool 不是独立类，而是一个变长 `TaggedArray` 的**特化**（`ConstantPool` 类包装它）。`TaggedArray` 的每个槽位是一个 `JSTaggedValue`（8 字节，可编码堆对象指针 / Smi 整数 / double / 特殊值）。

### 3.2 物理布局：用户区 + 尾部元数据

```text
偏移 0                         用户区（capacity 个槽）                尾部（9 槽 + 2 原生指针）
┌─────────────────────────────┬──────────────────────────────────────┐
│ TaggedArray header (16B)    │ data[0..capacity-1]                  │ data[capacity..]        │
│   Length = capacity+7+2     │ ← 字节码索引访问区                     │ ← 尾部元数据（反向定位） │
└─────────────────────────────┴──────────────────────────────────────┘
```

- **用户区**：`data[0..capacity-1]`，字节码索引直接访问；
- **尾部（`EXTEND_DATA_NUM=7` + `RESERVED_POOL_LENGTH=2`）**：存 `JSPandaFile*`、`IndexHeader*`、AOT 信息、shared/unshared 标识等，用 `GetLength() - 常量` 反向定位（`program_object.h:315-346`）。

### 3.3 初始化：Hole 填充

`NewConstantPool(capacity)`（`object_factory.cpp:3541`）→ `InitializeWithSpecialValue(Hole)`：**全部用户区槽位初始化为 Hole**，resolve 时再替换为真实值。

### 3.4 槽位类型（三种状态）

| 状态 | 含义 | 快照是否产生边 |
|---|---|---|
| **堆对象** | 已 resolve 的 Method / ClassLiteral / 字符串 / 对象 | 是（`element` 边） |
| **数字常量** | resolve 成 Smi / double（如数字字面量） | **否**（原始值不产生边） |
| **Hole** | 从未被 resolve（从未被访问） | 否 |

**这是快照分析最重要的坑**：快照里「无可见对象边」的槽位 = Hole + 数字常量，**不能直接当成 Hole**（见 §5.3）。

### 3.5 读写路径

- **读**：`GetObjectFromCache(thread, index)` → `Get(thread, index)`（`tagged_array.h` 直接按 `DATA_OFFSET + index*8` 寻址）；
- **写**：`SetObjectToCache(thread, index, value)`；shared 池并发首次写入用 `CASSetObjectToCache`（原子槽写入）；
- **生成代码**：`CircuitBuilder::GetObjectFromConstPool` / `StubBuilder::GetObjectFromConstPool` 也按 index 直接寻址（`circuit_builder.cpp:974-1005`、`stub_builder-inl.h:3176-3179`）——**没有边界检查**。

**推论**：如果缩小 ConstantPool 容量但字节码 index 不变，高 index 访问会越界。这就是「运行时稀疏化」被否决的根因（§7.2）。

### 3.6 GC 遍历

`DECL_VISIT_ARRAY(DATA_OFFSET, GetCacheLength(), GetLength())` 线性扫描引用区（`program_object.h:694`）；对象大小由 `TaggedArray::GetLength()` 计算（`js_hclass-inl.h:221-246`）。因此 `Length` 必须是物理长度，不能改成「逻辑容量」而只分配小数组。

---

## 4. 生命周期与持有者

ConstantPool 创建于 abc 加载时，生命周期与 abc 一致。持有者：

| 持有者 | 说明 |
|---|---|
| `Method::CONSTANT_POOL_OFFSET` | 每个 Method 持有一个 ConstantPool 引用（解释器/基线/JIT 直接加载） |
| `EcmaVM::unsharedConstpools_` | VM 根表（local 池，`ecma_vm.cpp:505-512`） |
| `Runtime::globalSharedConstpools_` | 全局 shared 池表（shared GC 遍历） |
| EcmaVM context cache | shared 池缓存 |

---

## 5. 快照观测：ConstantPool 的实际占用

### 5.1 总量（13 应用）

| 指标 | 值 |
|---|---|
| ConstantPool 数 | 4,049 个 |
| 用户区物理槽 | 40,102,399 个 × 8B ≈ 305.96 MiB |
| 尾部 + 原生指针槽 | 4049 × 9 × 8B ≈ 0.29 MiB |
| **合计** | **306.30 MiB**（占 heap_self 约 18.6%） |
| 可见 `element` 边（堆对象槽） | ~180 万个 ≈ 14.4 MiB |

### 5.2 jingdong 触顶案例

105 个池 cap 均为 65,543（method_idx_size 触顶 65,536），单池 524 KB，填充率 0.04%–2.62%——**虚高容量的确定性浪费**。

### 5.3 「填充率低」≠「全是 Hole」

- 数字常量（Smi/double）resolve 后**不产生快照边**；
- 因此「无可见对象边」≈ 292 MiB 是 **Hole + 数字常量** 的上界，不是 Hole 本身；
- 区分两者需要 VM 插桩做**槽位值分类**（`max_read_index`、每槽最终值类型）。

---

## 6. 相关对象

| 对象 | 与 ConstantPool 的关系 | 快照规模 |
|---|---|---|
| `Method` | 池里最常见的条目（~54%），每个 Method 反向持有池 | 100.42 MiB |
| `ClassLiteral` | 类字面量条目（~17%），由池强引用 | 4.85 MiB |
| `FunctionTemplate` | 由 cow_tagged_array 持有，间接关联 | 36.39 MiB |
| `EcmaString` | 字符串条目（~17%），intern 去重 | 83.03 MiB |

---

## 7. 优化方向

### 7.1 编译器侧：method_idx_size 缩减（推荐，方案 13）

在 abc 打包时做死方法 DCE + 全量重编号，把 `method_idx_size` 从虚高值压到实际存活方法数 → ConstantPool 容量直接缩小。jingdong 单应用 ~50 MiB 量级。**与运行时边语义无关，是编译产物的确定性浪费**。

### 7.2 运行时侧：为什么被否决（250–280 MiB 不成立）

原「稀疏化」声称按填充率（4.5%）把池缩到 10% 容量可省 250–280 MiB，但：

1. 「无可见对象边」≠ Hole（数字常量不产生边，见 §5.3）；
2. 连续数组容量取决于**最高访问 index**，不取决于已填槽数；
3. 字节码 index 编译期固定 + 生成代码无边界检查，缩容会越界（§3.5）；
4. 备选 `NumberDictionary` 稀疏后端空间模型不成立（10% 填充已 49.2% 空间）。

### 7.3 需要插桩确认的前置

| 必测量 | 目的 |
|---|---|
| 每池 `max_read_index` / `max_write_index` / index 直方图 | 判断按最高 index 截断是否有前缀收益（review 试算 ~50 MiB） |
| 每槽最终值分类（Hole / 原始值 / 堆对象） | 把 292 MiB 上界收敛成真实 Hole 量 |
| 编译器侧静态可达方法数 vs `method_idx_size` | 量化方案 13 的 DCE 空间 |

---

## 8. 术语表

| 术语 | 含义 |
|---|---|
| abc | ArkTS 字节码文件（编译产物） |
| ConstantPool | 字节码索引 → 运行时堆对象的映射数组（变长 TaggedArray） |
| `IndexHeader` | abc 索引区头，含 `method_idx_size` 等各索引空间大小 |
| `method_idx_size` | 方法索引条目数，直接决定 ConstantPool 容量（上限 65,536） |
| Hole | 特殊值，表示槽位未被 resolve |
| `JSTaggedValue` | 8 字节标签值，可编码堆对象指针 / Smi / double / 特殊值 |
| `element` 边 | 快照中数组槽位持有堆对象时产生的边 |
| unshared / shared 池 | local 池（每 VM 一份）vs shared 池（sendable 对象跨线程共享） |

---

## 附：源码位置索引

| 事实 | 位置 |
|---|---|
| `IndexHeader` 结构 | `runtime_core/libpandafile/file.h:81-92` |
| 指令操作数引用常量池 | `runtime_core/static_core/isa/isa.yaml`（lda.str:435、newobj:2274、ldobj:2358、call.range:2743） |
| ConstantPool 布局/尾部 | `ecmascript/jspandafile/program_object.h:315-346` |
| `NewConstantPool` | `ecmascript/object_factory.cpp:3541` |
| 读/写/CAS | `program_object.h:460-537` |
| GC 遍历 | `program_object.h:694`、`ecma_macros.h:741-746` |
| 生成代码直接寻址 | `circuit_builder.cpp:974-1005`、`stub_builder-inl.h:3176-3179` |
| 池持有者 | `ecma_vm.cpp:505-512`、`runtime.cpp:662-724` |