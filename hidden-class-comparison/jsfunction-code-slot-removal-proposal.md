# JSFunction 代码槽移除方案

## 1. 方案概览

JIT 关闭构建中，`JSFunction` 的 `MachineCode` 和 `BaselineCode` 两个 8 B 槽始终为 `Undefined`。本方案在该构建档位中删除这两个槽，将 `JSFunction::SIZE` 从 112 B 降至 96 B。

| 指标 | 数值 |
|---|---:|
| 单实例毛收益 | 16 B |
| Top13 完整尾部实例 | 2,830,994 |
| `ENABLE_API_FUNCTION_OPTIMIZATION` 关闭时毛收益 | 43.198 MiB，占 Top13 `heap_self` 2.62% |
| `ENABLE_API_FUNCTION_OPTIMIZATION` 开启时毛收益 | 31.138 MiB，占 1.89% |
| 工作量 | 62 人日 |
| 排期 | 5–6 周 |

方案仅适用于构建期确定的无 JIT 产品档位。该档位不能在运行时启用 Fast JIT 或 Baseline JIT。

## 2. 布局与适用范围

### 2.1 当前布局

函数对象分为两个主要尺寸档位：

| 类 | 固定尺寸 | 尾部字段 | 典型对象 |
|---|---:|---|---|
| `JSApiFunction` | 80 B | 截止到 `HomeObject` | NAPI 函数 |
| `JSFunction` | 112 B | 增加 `RawProfileTypeInfo`、`MachineCode`、`BaselineCode`、`Module` | ArkTS 函数及完整尾部派生类 |

本基线启用了 `ENABLE_MEMORY_OPTIMIZATION`，`WorkNodePointer` 不占槽。112 B 是当前 `JSFunction` 固定尺寸。

Heap Snapshot 的函数 `self_size` 还包含 HClass 定义的 in-object property 槽。例如 bilibili 样本中，完整尾部函数主峰为 144 B，等于 112 B 固定尺寸加 32 B 内联槽；NAPI 函数主峰为 112 B，等于 80 B 固定尺寸加 32 B 内联槽。

### 2.2 目标布局

```text
当前                         JIT 关闭构建
80  RawProfileTypeInfo       80  RawProfileTypeInfo
88  MachineCode             88  Module
96  BaselineCode            96  LAST_OFFSET
104 Module
112 LAST_OFFSET
```

布局变化：

- 删除 `MachineCode` 和 `BaselineCode`；
- `Module` 从偏移 104 前移到 88；
- `JSFunction::SIZE` 从 112 B 降至 96 B；
- GC 扫描区间减少两个 Tagged slot；
- `JSObject`、`JSFunctionBase` 和 `JSApiFunction` 的布局不变。

### 2.3 适用条件

1. 通过 GN arg 和编译期 define 建立无 JIT 构建档位。
2. Fast JIT、Baseline JIT、deoptimizer 及其机器码安装路径不进入该构建。
3. snapshot、heap image、AOT 文件和 rawheap metadata 携带布局版本。
4. 布局版本不匹配时拒绝加载。
5. stub、LiteCG、trampoline、serializer 和诊断代码不保留被删除槽的 offset。

运行期 JIT 开关不能承担布局选择。运行期可能在 HClass 建立后才关闭 JIT，也可能重新启用 JIT；此时已按 96 B 分配的对象没有存放机器码的位置。

## 3. 与 ENABLE_API_FUNCTION_OPTIMIZATION 的关系

`ENABLE_API_FUNCTION_OPTIMIZATION` 影响 NAPI 函数使用的尺寸档位：

- 宏关闭：NAPI 创建路径使用 112 B `JSFunction`；
- 宏开启：NAPI 创建路径使用 80 B `JSApiFunction`。

该宏不删除字段，也不改变类定义。它只决定 NAPI 函数使用哪种 HClass 和对象尺寸。

| 场景 | 可优化实例 | 单实例收益 | Top13 毛收益 |
|---|---:|---:|---:|
| 宏关闭 | 2,830,994 | 16 B | 43.198 MiB |
| 宏开启 | 2,040,682 | 16 B | 31.138 MiB |
| 宏开启后转入 `JSApiFunction` 的 NAPI 实例 | 790,312 | 0 | 收益减少 12.059 MiB |

宏开启时，NAPI 函数已停在 80 B 档，不含两个代码槽，不能重复计算本方案收益。该比例按快照存活实例统计，不代表函数创建次数。逐应用数据和 NAPI 判据见附录 B。

## 4. 收益口径

### 4.1 可优化对象

| 对象 | 是否含代码槽 | 收益 |
|---|---|---:|
| 完整尾部 `JSFunction` 及派生类 | 是 | 16 B/实例 |
| `JSApiFunction` | 否 | 0 |
| `FunctionTemplate` | 否 | 0 |
| `JSProxy` | 否 | 0 |

Top13 包含 2,830,994 个完整尾部实例：

```text
2,830,994 × 16 B = 45,295,904 B = 43.198 MiB
```

Top13 快照 `heap_self` 总量为 1,647.963 MiB，毛收益占 2.62%。

### 4.2 口径边界

- `JSApiFunction` 不含代码槽，收益为 0。
- `ENABLE_MEMORY_OPTIMIZATION` 已生效，`WorkNodePointer` 的 8 B 不计入本方案。
- `ENABLE_API_FUNCTION_OPTIMIZATION` 开启后，应使用 31.138 MiB，不能与 43.198 MiB 相加。
- `RawProfileTypeInfo` 不在本方案范围内。
- 该收益是对象浅层字节毛收益。GC committed/resident 和 PSS 需实测。

## 5. 实施范围

### 5.1 构建档位

增加无 JIT 编译期档位，并在该档位中：

- 固定 JIT 启用判断为 false；
- 不编译 Fast JIT、Baseline JIT 和 deoptimizer 访问路径；
- 生成与 96 B 布局匹配的 stub 和 trampoline；
- 使用独立布局版本。

现有 JIT 启用判断集中在 PostFork 路径，可复用启用侧判定。对象布局、stub 常量和汇编立即数仍需编译期裁剪。

### 5.2 字段和直接访问

非测试代码影响 19 个文件、39 处：

| 类别 | 处数 | 文件数 | 处理方式 |
|---|---:|---:|---|
| C++ 访问器 | 27 | 11 | 在无 JIT 构建中裁剪 |
| 按 offset 直接访问 | 12 | 9 | 删除或替换为无 JIT 路径 |

按 offset 直接访问包括：

- compiler stub 和 LiteCG 3 处；
- aarch64/x64 trampoline 4 处；
- serializer 4 处；
- 栈回溯 1 处。

测试侧还需更新 5 处 offset 断言和 4 处访问器用例。

### 5.3 不受影响的接口

| 项 | 影响 |
|---|---|
| 字节码格式 | 无 |
| 公开 API 与 SDK 版本 | 无 |
| NAPI 接口语义 | 无 |
| ArkTS 可观察语义 | 无 |
| `JSHClass` 布局 | 无 |
| `JSApiFunction` 尺寸 | 保持 80 B |

JIT 和 deoptimization 在该构建中不可用，这是产品档位的适用条件。

## 6. 风险与验证

| 风险 | 等级 | 控制条件 |
|---|---|---|
| 缺少 JIT 编译期总开关 | 高 | 建立 GN arg 和 define；裁剪 JIT/deoptimizer/Baseline 路径 |
| trampoline 直接读取 offset | 高 | aarch64/x64 分别构建并真机验证 |
| 布局版本混用 | 高 | snapshot、AOT、rawheap 统一版本校验 |
| 运行时启用 JIT | 高 | 无 JIT 构建不提供启用入口 |
| serializer 偏移特判 | 中 | 删除两个槽的 case；验证跨版本拒绝加载 |
| 栈回溯定位 | 中 | 使用无 JIT 帧路径 |
| metadata 测试 | 低 | 更新 offset 与间距断言 |

### 6.1 构建和功能验证

- x64 host 构建；
- aarch64 产品构建和真机启动；
- 解释器、IC、PGO 和 AOT；
- ArkTS 函数、async/generator、类构造函数和内建函数；
- NAPI 函数在宏开启和关闭两种配置下运行；
- serializer、snapshot、AOT 和 rawheap 跨版本拒绝加载；
- debugger、profiler、heap dump 和栈回溯；
- full GC 与 heap verification。

### 6.2 收益验证

- Top13 两版快照按同一采集点对比；
- 完整尾部函数固定尺寸减少 16 B；
- 宏开启时只统计非 NAPI 完整尾部实例；
- 对象数量保持可比；
- 单独报告浅层堆、GC committed/resident 和 PSS；
- 解释理论字节差与实测差异。

## 7. 工作量与排期

| 任务 | 设计 | 开发 | 测试 | 小计 |
|---|---:|---:|---:|---:|
| 无 JIT 构建档位及条件编译 | 1 | 3 | 3 | 7 |
| 字段删除、offset 和访问器联动 | 1 | 5 | 3 | 9 |
| compiler stub / LiteCG | 1 | 3 | 2 | 6 |
| aarch64/x64 trampoline | 2 | 5 | 4 | 11 |
| serializer | 1 | 2 | 2 | 5 |
| 栈回溯 | 0 | 2 | 2 | 4 |
| 布局版本和拒绝加载 | 1 | 3 | 3 | 7 |
| 诊断工具与测试适配 | 0 | 3 | 3 | 6 |
| 内存实测与性能回归 | 1 | 0 | 6 | 7 |
| **合计** | **8** | **26** | **28** | **62 人日** |

按 1 名运行时开发、1 名 compiler 开发、1 名测试工程师并行，关键路径约 5–6 周。构建档位是其他任务的前置；aarch64/x64 trampoline 验证位于关键路径。

## 8. 评审决策项

| 编号 | 事项 | 说明 |
|---|---|---|
| F1 | 目标产品是否开启 `ENABLE_API_FUNCTION_OPTIMIZATION` | 决定采用 43.198 MiB 还是 31.138 MiB 收益口径 |
| F2 | 无 JIT 档位的产品范围 | 确认产品变体和产物版本策略 |
| F3 | trampoline 实现 | 条件编译裁剪或独立无 JIT trampoline |
| F4 | 验收指标 | 确认内存、启动、解释器和 AOT 回归阈值 |

`RawProfileTypeInfo` 槽涉及 IC feedback，不纳入本方案。若评估该槽，应建立独立方案和工作量。

---

## 附录 A：源码证据

基线仓库为 `arkcompiler/ets_runtime`。本基线 `js_runtime_config.gni:89` 中 `ets_runtime_feature_enable_list = false`。

### A.1 布局

| 事实 | 源码位置 |
|---|---|
| `JSFunctionBase` / `JSApiFunction` / `JSFunction` 布局 | `ecmascript/js_function.h:185-256,480-501` |
| `JSObject` 头部和字段 | `ecmascript/js_object.h:379,722` |
| 函数 in-object capacity | `ecmascript/js_hclass.h:418` |
| 代码槽初始化为 Undefined | `ecmascript/js_function.cpp:110-111` |
| `MachineCode` JIT 回填 | `ecmascript/jit/jit_task.cpp:386` |
| `BaselineCode` JIT 回填 | `ecmascript/jit/jit_task.cpp:403` |
| deopt 清空和函数复制 | `ecmascript/deoptimizer/deoptimizer.cpp:684`；`ecmascript/js_function.cpp:1379,1406-1407` |
| API 函数访问器类型检查 | `ecmascript/js_function.h:487-500` |
| API 函数复制分支 | `ecmascript/js_function.cpp:1389-1390`；`ecmascript/object_factory.cpp:682` |

### A.2 ENABLE_API_FUNCTION_OPTIMIZATION

| 生效位置 | 作用 |
|---|---|
| `ecmascript/napi/jsnapi_class_creation_helper.cpp:156,181` | 切换 HClass 和构造函数 |
| `ecmascript/napi/jsnapi_expo.cpp:3828,3857,3886` | `FunctionRef` 使用 API 函数档位 |
| `ecmascript/napi/jsnapi_expo.cpp:3991,4027,4095` | NAPI 类函数使用 API 函数档位 |
| `ecmascript/object_factory.cpp:1959,2312,5909` | API 函数实例和 HClass 创建 |
| `ecmascript/builtins/builtins.cpp:287-289,744-746` | API 函数 HClass 创建 |
| `ecmascript/js_function.cpp:1110-1149` | `SetFunctionExtraInfo` |

### A.3 直接 offset 访问

| 位置 | 用途 |
|---|---|
| `ecmascript/compiler/stub_builder-inl.h:3770` | `MACHINECODE_OFFSET` |
| `ecmascript/compiler/call_stub_builder.cpp:751` | `BASELINECODE_OFFSET` |
| `ecmascript/compiler/codegen/maple/litecg_ir_builder.cpp:751` | `MACHINECODE_OFFSET` |
| `ecmascript/compiler/trampoline/aarch64/asm_interpreter_call.cpp:1712` | `BASELINECODE_OFFSET` |
| `ecmascript/compiler/trampoline/aarch64/optimized_call.cpp:1381` | `BASELINECODE_OFFSET` |
| `ecmascript/compiler/trampoline/x64/asm_interpreter_call.cpp:719` | `BASELINECODE_OFFSET` |
| `ecmascript/compiler/trampoline/x64/optimized_call.cpp:1421` | `BASELINECODE_OFFSET` |
| `ecmascript/dfx/stackinfo/js_stackinfo.cpp:866` | `MACHINECODE_OFFSET` |
| `ecmascript/serializer/base_serializer.cpp:211-212,343-344` | serializer offset case |
| `ecmascript/dfx/hprof/tests/js_metadata_test.cpp:675-676,1465-1467` | offset 与间距断言 |

### A.4 构建期条件

| 事实 | 源码位置 |
|---|---|
| PostFork JIT 启用判断 | `ecmascript/jit/jit.cpp:57-81`；`ecmascript/ecma_vm.cpp:308` |
| 低机器码内存标志可恢复 | `ecmascript/jit/jit.cpp:452-459`；`ecmascript/js_thread.h:2278-2286` |
| JIT 运行期选项 | `ecmascript/js_runtime_options.h:1420-1425` |
| Baseline JIT 运行期选项 | `ecmascript/js_runtime_options.cpp:394` |
| 运行中启停 | `ecmascript/jit/jit.cpp:192-196` |
| deoptimizer 无条件参与构建 | `ecmascript/BUILD.gn:1013-1014` |
| stub 构建期生成 | `ecmascript/compiler/BUILD.gn:619-709` |
| AOT 版本常量 | `ecmascript/compiler/aot_file/aot_version.h:28-30` |
| rawheap metadata version | `ecmascript/dfx/hprof/script/metadata_generate.py:74` |

## 附录 B：Top13 原始数据

输入为 `D:\docker\plan\top13` 的 13 个 `.rawheap`，使用 DevEco SDK 6.1 的 `rawheap_translator` 转换。参照结果为 `team_interop/analysis/top13-jit-off/top13-jit-off-estimates.csv`。

### B.1 NAPI 判据

`JSType` 位于 HClass，实例固定尺寸由 HClass 的 `ObjectSize` 决定，因此先按 HClass 判断完整尾部，再统计该 HClass 的实例。

NAPI 创建路径调用 `JSFunction::SetFunctionExtraInfo`。该函数把 `JSNativePointer` 写入 `HashField`，或写入 `Properties` 中的 `TaggedArray`。统计使用该链路识别 NAPI 创建的完整尾部实例。内建函数和 `FunctionTemplate` 不走该路径，不计入 NAPI 数。

### B.2 逐应用数据

| 应用 | 完整尾部实例 | NAPI 创建 | NAPI 占比 |
|---|---:|---:|---:|
| wechat | 151,106 | 13,813 | 9.14% |
| weibo | 423,280 | 71,326 | 16.85% |
| douyin | 439,425 | 77,907 | 17.73% |
| bilibili | 79,400 | 14,163 | 17.84% |
| jrtt | 207,996 | 40,266 | 19.36% |
| taobao | 98,336 | 19,787 | 20.12% |
| gaodeditu | 75,279 | 15,653 | 20.79% |
| jingdong | 267,009 | 63,077 | 23.62% |
| meituan | 207,955 | 54,914 | 26.41% |
| alipay | 184,291 | 52,064 | 28.25% |
| pinduoduo | 181,106 | 59,100 | 32.63% |
| meituanzhongbao | 132,498 | 46,908 | 35.40% |
| kuaishou | 383,313 | 261,334 | 68.18% |
| **Top13 合计** | **2,830,994** | **790,312** | **27.92%** |

```text
宏关闭收益 = 2,830,994 × 16 B = 43.198 MiB
宏开启收益 = (2,830,994 - 790,312) × 16 B = 31.138 MiB
宏开启收益减少 = 790,312 × 16 B = 12.059 MiB
```

`kuaishou` 的 NAPI 占比为 68.18%，其他应用为 9.14%–35.40%。剔除该样本后，NAPI 占比为 21.61%，宏开启收益减少 8.072 MiB，剩余收益 29.277 MiB。
