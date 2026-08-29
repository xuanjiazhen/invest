# NAPI Prototype Native 方法按需绑定技术方案评审提案

| 项目 | 内容 |
|------|------|
| 文档日期 | 2026-08-28 |
| 源码基线 | `OpenHarmony-7.0-Release@4ad97323...`；`arkcompiler_ets_runtime@f04900cf`；`foundation/arkui/napi@464170c9` |
| 设计范围 | `napi_define_class` 注册的 prototype native method |
| 方案状态 | 设计评审； |

## 一、摘要（Executive Summary）

本方案针对 `napi_define_class` 注册期间为未读取的 prototype native method 在实际使用前提前创建完整 JavaScript 函数对象图的问题，目标是减少注册期的无效对象创建。

方案仅对普通、非 Sendable 类的非 static prototype method 安装 VM 内部惰性方法槽，注册期保存 `{method, data}`，首次读取时复用现有 `NapiNativeCreateFunction` 和 `FunctionRef::NewConcurrentWithName` 创建链，并在同一 property slot 写回 `JSFunction`。

设计容量收益为每个未物化方法避免一组注册期函数对象，但 `NapiLazyAccessor`、recipe、状态目录和生命周期管理的实际计费尚未测量。目标验收值为：注册 P95 相对基线回退不超过 1%，首次读取 P95 增量不超过 `0.10 ms/方法`，稳态吞吐不低于基线 99%；RSS/PSS 收益必须通过 clean A/B 实测确认。

## 二、背景与现状（仅面向开发者视角）

### 2.1 业务痛点

开发者使用 Node-API 注册包含大量 prototype native method 的类时，`napi_define_class` 返回前会创建所有目标方法的 `JSFunction`、`JSNativePointer` 和 `NapiFunctionInfo`。即使业务代码从未读取某个方法，prototype property slot 仍然持有该函数对象。

当前证据显示，Top13 应用 method closure population 为 447,707 个、占用约 61.474 MiB；快手为 175,025 个、约 24.035 MiB。上述数据是快照对象关系统计，不是创建侧的 eligible method census，不能直接作为本方案已实现收益。

开发者可观察的影响包括：类注册阶段的分配次数增加，未使用方法的函数对象进入 prototype 可达图，以及首次页面或模块加载阶段出现与方法数量相关的注册工作。注册耗时、RSS/PSS 和首次读取时延的基线数值目前为 `[待核实：请在此处补充同一产品、同一操作序列下的 clean A/B 基线数据]`。

### 2.2 现有架构局限性

当前调用链为：

```text
napi_define_class
  -> NapiDefineClass
  -> NapiCreateClassFunction
  -> NapiGetKeysAndAttrsFromProps
  -> NapiInitAttrValFromProp
  -> NapiNativeCreateFunction
  -> FunctionRef::NewConcurrentWithName
```

源码位置：

- `D:\docker\invest\foundation\arkui\napi\native_engine\native_api.cpp:1643-1674`
- `D:\docker\invest\foundation\arkui\napi\native_engine\impl\ark\ark_native_engine.cpp:190-369`
- `D:\docker\invest\arkcompiler\ets_runtime\ecmascript\napi\jsnapi_expo.cpp:3947-4039`

`NapiNativeCreateFunction` 当前为每个目标 method 创建 `NapiFunctionInfo`；目标方案冻结版本的 AArch64 record-layout probe 给出 `NapiFunctionInfo` 为 32 B 或 40 B，`JSFunction` 设计值为 144 B，`JSNativePointer` 设计值为 40 B。malloc usable size、Region committed、RSS/PSS 尚未测量。

prototype HClass/LayoutInfo 记录属性 key、`PropertyAttributes`、offset 和 `TAGGED` representation；当前 prototype slot 保存 `JSFunction`。惰性方案必须保持这些属性元数据不变。涉及当前 property lookup、IC、反射入口是否全部可拦截的事实，标记为 `[待核实：请在此处补充源码文件绝对路径 + 行号]`。

## 三、需求目标与红线（Goals & Non-Goals）

### 3.1 核心目标

1. **注册期目标**：对符合条件的 prototype method 不创建 `JSFunction`、`JSNativePointer` 和 `NapiFunctionInfo`；注册 P95 相对基线回退不得超过 1%，超过即关闭开关。
2. **运行期目标**：首次读取返回与即时路径等价的 `JSFunction`，首次读取 P95 增量不得超过 `0.10 ms/方法`；稳态吞吐不得低于基线 99%。
3. **语义目标**：公开 Node-API ABI、函数 identity/name/length、数据属性 W/E/C、反射、GC 和 Sendable 行为与基线一致；出现 UAF、double-free、未捕获崩溃或属性语义差异时自动回滚。

### 3.2 非目标

- 不修改公开 `napi_define_class` 签名、`napi_property_descriptor` ABI 或字节码格式。
- 不修改 `JSFunction`、`JSNativePointer`、HClass、LayoutInfo、GC 对象布局、snapshot schema、IC/AOT 编译器数据结构。
- 不处理 constructor、static method、getter/setter、纯 value property 和 Sendable 类；这些路径继续即时创建。
- 不承诺消除 `JSFunction` 或 `JSNativePointer` 的创建；首次读取后它们仍按现有生命周期存在。
- 不承诺修复动态库卸载后的 callback 地址有效性；module pin 需要独立方案。

## 四、方案选型与决策依据（剔除垃圾讨论）

### 4.1 备选方案对比

| 方案 | 核心思路 | 否决原因或适用边界 |
| :--- | :--- | :--- |
| **C2（最终采用）** | 首次读取时创建 prototype method 函数对象图，并写回普通数据属性 | 修改 property lookup、反射、IC 失效、GC 可见性和生命周期；实现范围最大，但能减少未读取方法的函数对象驻留 |
| B1 | 首次调用时创建并回写 `NapiFunctionInfo` | 需要保存等价 cold record，存在首调分配、并发和 old/new metadata 同时驻留问题 |
| B2 | 复用 `JSNativePointer` 指针槽保存冷态信息 | 无法同时保存 callback、data、env 和 scopeId，且同一 VM 可有多个 environment |
| B3 | 按类 arena 分配完整函数 metadata | 可减少 allocation 次数，但不减少完整结构字节；适合生命周期 PoC |
| D1 | 每类 compact native metadata table | 仅改变堆外 metadata，不提供未创建 `JSFunction` 的收益；作为独立次方向，不与 C2 收益相加 |

### 4.2 最终方案设计

**注册阶段**：`NapiGetKeysAndAttrsFromProps` 继续创建 VM String/Symbol key 和 `PropertyAttributes`，并保持 static/prototype 分区及声明顺序。目标 prototype method 不调用即时函数创建链，而是保存以下新增记录：

```cpp
struct NativeLazyMethodRecipe {
    NapiNativeCallback method;
    void *data;  // non-owning
};
```

每个目标方法的 prototype slot 写入 VM 内部 `NapiLazyAccessor`，payload 保存 generation-safe token 和 recipe index。每类创建 `ClassBindingLifetime` 与原子 `slotDirectory`，状态至少包括 `LAZY`、`MATERIALIZING`、`DONE`、`DEAD`。recipe 只复制 callback/data 指针，不拥有 `data` 指向的资源。

```cpp
class NapiLazyAccessor : public Record {
    NativeReadEntry readEntry;
    NativeWriteEntry writeEntry;
    TaggedPayload payload;
};
```

`NapiLazyAccessor` 是 VM 内部普通 data property value，不得使 `JSTaggedValue::IsAccessor()` 或 `PropertyAttributes::IsAccessor` 置位。其最终 ABI 大小和 GC visitor 范围为 `[待核实：请在此处补充目标 ABI probe 文件路径与结果]`。

**首次读取阶段**：

1. property lookup 在实际 holder 上命中 `NapiLazyAccessor`，保存 receiver、holder 和当前 VM key。
2. 解析 token/index，获取 `ClassBindingLifetime` guard。
3. 以 CAS 将 `LAZY` 转为 `MATERIALIZING`；其他线程等待已发布结果或按失败协议返回。
4. 使用当前 key、recipe.method 和 recipe.data，复用 `NapiNativeCreateFunction` 与 `FunctionRef::NewConcurrentWithName` 创建 `JSFunction`、`JSNativePointer` 和 `NapiFunctionInfo`。
5. 写回前确认 holder 的 slot 仍保存相同 accessor；若已被覆盖或删除，释放新建函数图并按终态处理。
6. 通过带写屏障的专用路径在同一 slot 写入 `JSFunction`，保持 HClass、LayoutInfo、key、W/E/C、offset 和 `TAGGED` representation 不变。
7. 调用正式的 prototype change/IC invalidation API，发布 `DONE`，释放 recipe，并返回 `JSFunction`。

prototype 原位写回对应的正式 API、所有 LoadIC/StoreIC/runtime stub/AOT 读取入口及其源码路径为 `[待核实：请在此处补充源码文件绝对路径 + 行号]`。

**属性行为**：首次读取和 `Object.getOwnPropertyDescriptor` 只物化必要方法；`in`、`hasOwn`、键枚举不读取 value。prototype 自有槽的覆盖、删除、`defineProperty`、`freeze` 和 `seal` 必须先发布终态，再释放 recipe。receiver 自有属性覆盖不得误终止 prototype 上的 recipe。不可写、不可配置、Proxy/Reflect、Symbol key、重复 key 和严格模式行为必须与即时路径一致。

**生命周期**：environment teardown 先发布 `DEAD`，阻止新 guard 和新物化，等待在途 guard 排空，再释放未物化 recipe、目录和 token。已物化函数图继续由现有 GC/CommonDeleter 管理。cleanup hook 的完整顺序为 `[待核实：请在此处补充源码文件绝对路径 + 行号]`。recipe 不释放外部 `data`，table/registry 不提前释放 callback 所属动态库。

### 4.3 成本模型与已知收益边界

未物化方法的逻辑收益可写为：

```text
net_shallow = sum(avoided_eager_object_bytes
                  - lazy_accessor_actual
                  - recipe_allocator_actual)
              - directory_actual
              - lifetime_registry_actual
```

该公式只用于测试数据归因。`NativeLazyMethodRecipe` 的 16 B 是逻辑 payload，不是 allocator actual；`NapiLazyAccessor` 的 32 B 是设计值，不是已确认对象大小。Top13 的 61.474 MiB 和快手的 24.035 MiB 是 closure 存量，不得写成 C2 已实现收益。实际 native usable bytes、JS heap shallow、RSS/PSS 需要 clean A/B。

## 五、实施计划与灰度退出机制

### 5.1 实施计划

| 阶段 | 内容 | 预计人日 |
|------|------|---------:|
| 设计 | VM/NAPI 接口、对象布局、状态机、属性语义和错误传播定稿 | 4 |
| 开发 | 注册链、recipe、惰性槽、函数物化和 prototype 写回 | 21 |
| 开发 | lifetime、并发、cleanup、IC 失效与反射入口 | 6 |
| 测试 | 功能、属性语义、Sendable、GC、AOT、并发和 teardown | 13 |
| 测试 | allocator probe、clean A/B、RSS/PSS 与回归 | 4 |
| **合计** |  | **48** |

### 5.2 灰度观测指标

- `napi_define_class` 调用数、目标方法数、fallback 数和每类 `N/U`。
- 注册耗时 P50/P95/P99；首次读取耗时 P50/P95/P99；稳态吞吐。
- `NapiLazyAccessor`、recipe、directory 的 requested/usable/actual bytes 和 allocation count。
- full-GC 后 native heap committed、JS heap shallow/live、RSS/PSS。
- `libark_jsruntime.so` 相关 cppcrash、UAF、double-free、leak、异常退出和属性语义 DT 失败数。
- `freeze`、`seal`、Proxy、worker/environment teardown 和模块卸载场景的峰值分配与耗时。

### 5.3 回滚触发条件（SOP）

灰度阶段任一条件满足即关闭 C2 开关，恢复当前即时创建路径：

1. 崩溃率相对基线增加超过 1%，或出现任意可归因 UAF、double-free、native heap leak。
2. 注册 P95 相对基线回退超过 1%。
3. 首次读取 P95 增量超过 `0.10 ms/方法`。
4. 稳态吞吐低于基线 99%。
5. 任一属性 descriptor、函数 identity/name/length、Proxy、严格模式或 Sendable DT 失败。
6. RSS/PSS 在相同采样点重复测量中出现可归因回退，或 native usable bytes 未下降且新增管理成本超过 `0 B` 的待测红线。

## 六、破坏性变更清单（强制暴露负面影响）

| 影响维度 | 具体负面表现 | 缓解/适配措施 |
| :--- | :--- | :--- |
| 首次读取 | 首次读取新增 lookup、CAS、函数创建和 slot 写回延迟 | 单方法和批量首次读取分别压测；超过 `0.10 ms/方法` 自动回滚 |
| 分配峰值 | `freeze`、`seal`、序列化或批量枚举可能在短时间内物化多个函数 | 记录峰值和 P95；批量峰值超过基线 `+1 MB` 时停止灰度，具体基线待测 |
| VM 修改面 | property lookup、反射、IC invalidation、GC cleanup 需要识别内部惰性槽 | 使用独立 VM 类型和全入口 DT；无法覆盖的入口保持 legacy |
| 动态属性操作 | override、delete、`defineProperty`、Proxy 和环境销毁可能与物化并发 | 状态机、accessor identity 校验、guard drain 和 exactly-once 释放 |
| 三方 Node-API | 公开 ABI 不变，但 callback/data lifetime 与私有 trampoline 解释必须保持兼容 | 三方 native module 回归；不改变 `napi_property_descriptor` 布局 |
| DevEco Studio | 调试器和反射工具可能在首读前看到内部值，造成显示或断点行为差异 | 所有反射入口先物化；调试模式默认关闭开关，异常由 DT 捕获 |
| HAP/HSP | 本方案不改变字节码和 JS 源码，包体积增量目标为 `0 MB`；新增实现代码的包体积尚未测量 | build 产物对比；增量超过 `0.1 MB` 或 `1%` 取较大者时停止灰度 |
| 动态库卸载 | recipe 只保存 callback 地址，不延长 SO 生命周期 | 与即时路径做 unload 对照；不把 module pin 混入 C2 |

## 七、风险评估（仅保留与技术实现强相关项）

| 风险项 | 概率 | 影响描述 | 缓解动作 |
|---|---|---|---|
| 读取入口遗漏 | 中 | 某条 interpreter/IC/AOT/反射路径将内部槽直接返回给 JavaScript | 入口清单审计；每条路径执行首次读取和 descriptor DT |
| HClass/LayoutInfo 语义变化 | 中 | slot 写回触发错误 transition，导致属性描述符或 IC 结果变化 | 只允许同 slot TAGGED 写入；对比 HClass/LayoutInfo identity 和 W/E/C |
| 首读重复物化 | 中 | 多线程或重入产生多个函数对象、重复 callback metadata 或泄漏 | `LAZY -> MATERIALIZING` CAS；只发布一个结果并验证 exactly-once |
| override/delete 竞态 | 中 | recipe 提前释放或写回已被替换的 slot，导致 UAF | holder/accessor identity 校验；终态发布先于 free |
| teardown UAF | 中 | guard 未排空即释放 lifetime、recipe 或 token | `DEAD`、guard drain、GC/worker teardown 压测；ASan/LSan，支持时 TSan |
| allocator 成本抵消 | 高 | recipe、accessor、directory 和 registry 实际成本超过省下的对象 | 按 ABI 与 allocator actual/usable bytes 逐类测量；小类 fallback |
| Symbol/重复 key | 中 | 慢路径与重复 key throw 行为改变 | 保留当前 key 分区和异常路径；覆盖 Symbol、duplicate key DT |
| Sendable 误纳入 | 低 | 跨线程共享语义被改变 | Sendable 强制 legacy；增加类型和线程回归 |
| 动态库卸载 | 中 | callback 地址在 SO 卸载后失效 | 维持基线语义；不声称 C2 解决 module lifetime |

## 八、未决问题（Open Issues）

1. 当前分支是否提供可覆盖所有 interpreter、LoadIC/StoreIC、runtime stub、compiler/AOT、反射和 Proxy 入口的惰性槽识别点：`[待核实：请在此处补充源码文件绝对路径 + 行号]`。
2. `NapiLazyAccessor` 的目标 ABI 大小、`Record` factory 分配大小、GC visitor 范围和 verifier 规则：`[待核实：请在此处补充源码文件绝对路径 + 行号]`。
3. prototype 原位写回使用的正式 `JSHClass`/IC invalidation API 及其是否会影响 PGO `TrackType`：`[待核实：请在此处补充源码文件绝对路径 + 行号]`。
4. `ClassBindingLifetime` 与 environment cleanup 的并发顺序、guard drain 和 worker teardown 行为：`[待核实：请在此处补充源码文件绝对路径 + 行号]`。
5. 目标 AArch64 allocator 的 `malloc_usable_size`/等价接口结果，以及 `N=1..16` 的准入阈值：待 allocator probe。
6. Top13 和快手的创建侧 eligible method 数、每类 method 数、未读取比例和实际 `N/U` 分布：待 `napi_define_class` 创建侧插桩；快照 closure population 不作为替代数据。
7. 注册 P95、首次读取 P95、稳态吞吐、RSS/PSS、native committed 和 HAP/HSP 增量的基线及重复测量置信区间：待 clean A/B。
8. 首读失败、异常传播、`freeze`/`seal` 批量物化和 module unload 的产品级回滚开关：待运行时 DT 和灰度策略确认。

## 附录 A：术语-源码路径映射表

| 术语 | 含义 | 源码路径 |
|---|---|---|
| `EcmaVM` | ArkTS/JS 执行环境及生命周期主体 | `D:\docker\invest\arkcompiler\ets_runtime\ecmascript\ecma_vm.cpp` |
| `JSFunction` | JavaScript 函数对象 | `D:\docker\invest\arkcompiler\ets_runtime\ecmascript\js_function.cpp` |
| `JSNativePointer` | 函数 extra info 关联的 native pointer | `D:\docker\invest\arkcompiler\ets_runtime\ecmascript\js_native_pointer.h` |
| `NapiFunctionInfo` | 当前 NAPI callback/data/env/scope metadata | `D:\docker\invest\foundation\arkui\napi\native_engine\native_value.h:54-63` |
| `PropertyAttributes` | 属性 W/E/C、data/accessor 和表示信息 | `D:\docker\invest\arkcompiler\ets_runtime\ecmascript\` `[待核实：请在此处补充具体文件与行号]` |
| `JSHClass` | 对象 shape 和属性布局管理对象 | `D:\docker\invest\arkcompiler\ets_runtime\ecmascript\js_hclass*` `[待核实：请在此处补充具体文件与行号]` |
| `LayoutInfo` | 属性 key、attributes、offset 等布局信息 | `D:\docker\invest\arkcompiler\ets_runtime\ecmascript\layout_info*` `[待核实：请在此处补充具体文件与行号]` |
| `NapiDefineClass` | NAPI class 注册内部入口 | `D:\docker\invest\foundation\arkui\napi\native_engine\impl\ark\ark_native_engine.cpp:333-369` |
| `FunctionRef::NewConcurrentWithName` | 创建 native `JSFunction` 与 extra info 的入口 | `D:\docker\invest\arkcompiler\ets_runtime\ecmascript\napi\jsnapi_expo.cpp:3947-4039` |
| `RunCleanupHooks` | NAPI environment cleanup hook 执行入口 | `D:\docker\invest\foundation\arkui\napi\native_engine\native_engine.cpp:863-906` |
| `NapiLazyAccessor` | 本方案新增的 VM 内部惰性值类型 | 本方案设计类型，源码路径待实现 |
| `ClassBindingLifetime` | 本方案新增的类级生命周期对象 | 本方案设计类型，源码路径待实现 |

## 附录 B：验收数据表

| 指标 | 基线 | C2 | 红线 |
|---|---:|---:|---:|
| 注册 P95 | 待测 | 待测 | 相对基线回退 ≤1% |
| 首次读取 P95 | 待测 | 待测 | 增量 ≤0.10 ms/方法 |
| 稳态吞吐 | 待测 | 待测 | ≥基线 99% |
| native usable bytes | 待测 | 待测 | 不得因 C2 增加 |
| RSS/PSS | 待测 | 待测 | clean A/B 不得可归因回退 |
| HAP/HSP 体积 | 待测 | 待测 | 增量 ≤max(0.1 MB, 基线 1%) |
| 崩溃率 | 待测 | 待测 | 相对基线增加 ≤1% |

本提案只有在源码入口、对象布局、allocator actual、生命周期 DT 和 clean A/B 均完成验证后，才具备进入默认灰度范围的条件。
