# JSHClass 分档对象布局优化方案（基于 JIT 分档）

## 1. 背景问题

在 ArkVM 中，`JSHClass` 并不是用户代码里显式声明的对象类型，而是 VM 为“每一种对象形状”维护的一张内部布局描述表。它负责记录对象当前有哪些属性、这些属性在实例对象中的偏移位置、是否可枚举、是否可写，以及后续属性新增时的 transition 方向。

这意味着：无论是应用侧写 `class`、还是通过 `Object.defineProperty` 动态添加属性，VM 在内部都会为这类对象形状生成或切换一个新的 `JSHClass`。从应用视角看，`JSHClass` 是“对象形状描述符”（shape descriptor），而不是业务对象本身；它隐藏在对象创建、属性增删、枚举、原型链访问的背后。

典型的用户代码会触发这类内部对象布局创建，例如：

```js
class MyButton {
  title = '';
  onClick() {}
}

const obj = { a: 1, b: 2 };
obj.c = 3;

Object.defineProperty(obj, 'x', { value: 1 });
```

这些代码在 VM 内部都会走到 `JSHClass` 的初始化、克隆或 transition 路径：

- `class MyButton { ... }` 在对象创建时会形成带有固定属性布局的 `JSHClass`；
- `const obj = { a: 1, b: 2 }` 会创建一个初始 shape；
- `obj.c = 3` 会触发一次新的 shape 过渡；
- `Object.defineProperty(obj, 'x', { value: 1 })` 又会让 VM 继续在 shape 层面产生新的布局描述。

当前 64 位 ArkVM 中，`JSHClass` 的固定描述符尺寸为 88B。它不仅承载对象形状本身，还携带一组在不同执行阶段中会被访问的辅助元数据字段。这些字段中，`Proto`、`Layout`、`Transitions`、`Parent` 属于“形状继续存在所必须的骨架信息”；而 `ProtoChangeMarker`、`ProtoChangeDetails`、`EnumCache`、`DependentInfos` 则更偏向“在原型变化、枚举、依赖失效等旁路场景下才需要补齐”的辅助信息。

这部分辅助信息在当下统一保留为对象内联字段时，会带来两个直接后果：

1. 每个 `JSHClass` 都固定多出一组 8B 指针槽位，导致对象描述符被拉大；
2. 在低代码内存 / 低档机部署场景下，运行时会直接走“不启用 JIT 编译”路径，因此这些字段在多数实例中并不具备持续的使用价值。

从源码事实看，JIT 决策路径是“按运行时状态分档”的：当 VM 进入低代码内存状态时，编译路径会被主动跳过。这说明 `JSHClass` 的对象布局并不一定需要在所有部署态下维持一套“完整、全量、常驻”的辅助字段集合，而应视资源能力与 JIT 使能状态进行分档。

## 2. 解决思路和初步方案

### 2.1 归纳结论

`JSHClass` 的优化点，不应只停留在“减掉一个字段”，而应该建立一套明确的分档模型：

- 低档机 / 无 JIT：最小化 `JSHClass` 的内联字段集合，只保留对象形状必需的稳定字段；
- 中档机 / 轻量 JIT：保留最小骨架，但让可选型元数据按需补齐；
- 高档机 / 完整 JIT：保留当前的完整能力，但仍对极少使用的副字段做延迟化与分层化收敛。

因此，最有效的实现路径，是把 `JSHClass` 中的字段拆成两类：

- 必须保留的稳定元数据：`Proto`、`Layout`、`Transitions`、`Parent`
- 可选辅助元数据：`ProtoChangeMarker`、`ProtoChangeDetails`、`EnumCache`、`DependentInfos`

其中，后者更适合走“按需分配 + side table 化 + lazy 访问”的路径。

### 2.2 分档方案

#### 档位 A：低档机 / 无 JIT 分档

目标：在没有 JIT 编译机会的部署环境中，`JSHClass` 只保留最小的形状定义信息，避免把一套编译辅助字段永久内联在每个实例上。

保留：

- `Proto`
- `Layout`
- `Transitions`
- `Parent`

外迁或改为 lazy side table：

- `ProtoChangeMarker`
- `ProtoChangeDetails`
- `EnumCache`
- `DependentInfos`

方案要点：

- 默认只保留对象形状的稳定状态；
- 将原型变化、枚举缓存、依赖信息统一收束到 side table；
- 只在真实访问这些能力时，才补齐对应元数据对象。

这意味着：在低档部署中，`JSHClass` 的固定布局可以明显更轻，且不会因为“JIT 形态下才有用”的字段而牺牲每个实例的基础尺寸。

#### 档位 B：中档机 / 轻量 JIT 分档

目标：允许 JIT 参与，但不在对象创建阶段默认预分配整套辅助字段。

方案：

- 默认仍保持最小稳定布局；
- `ProtoChangeMarker` / `ProtoChangeDetails` / `EnumCache` 只在发生原型变化或枚举需要时才补齐；
- `DependentInfos` 采用弱关联记录，尽量不通过对象内联字段常驻持有。

这一档可以理解为：

- JIT 仍然存在，但并不是“每个 `JSHClass` 都自动拥有完整副字段集合”；
- 对象描述符在创建时只保留最基本的能力，并允许后续按需扩容。

#### 档位 C：高档机 / 完整 JIT 分档

目标：在高端部署环境下保持现有功能完整性，但仍然减少固定内联辅助字段带来的过度占用。

方案：

- 保留完整 JIT 能力的入口与编译态反馈机制；
- 但对长期不触发的 `ProtoChange*` / `EnumCache` / `DependentInfos` 做 lazy data ownership；
- 让这些元数据尽量在运行时按需挂载，而不是在对象初始化时全部完成。

## 3. 预估收益

### 3.1 以 140,000 个对象规模估算

从 `JSHClass` 固定内联字段看，`ProtoChangeMarker`、`ProtoChangeDetails`、`EnumCache`、`DependentInfos` 四个字段合计对应 32B 的固定内存占用。

如果将这四个字段从对象内联布局中移出，改为 side table 或惰性分配，则单个 `JSHClass` 的固定占用可从 88B 收敛为：

$$
88B - 32B = 56B
$$

对应到 140,000 个 `JSHClass` 描述符的规模，可得到毛节省：

$$
140{,}000 \times 32B = 4{,}480{,}000B \approx 4.27MiB
$$

### 3.2 额外收益：JIT 分档带来的布局层级收益

如果进一步把 `JSHClass` 的可选辅助字段按三档切换能力分拆，那么收益并不仅限于 4.27MiB 这一项直接节省：

- `JSHClass` 的固定描述符尺寸下降；
- 低档机时对象形状字段与编译辅助字段解耦；
- GC / heap snapshot 对对象描述符的浅层大小压力下降；
- JIT 决策路径与对象布局路径可以统一纳入“按需启用”的机制。

这条路径的收益体现方式是：

- 低档机场景下，类描述符更接近“最小执行布局”；
- 中高档场景下，JIT 能力仍然主要保留，但不再以“全面内联”的方式诱导对象体积膨胀。

## 4. 预估工作量

### 4.1 方案实施拆分

1. `JSHClass` 字段分档与外迁设计
   - 将 `ProtoChangeMarker` / `ProtoChangeDetails` / `EnumCache` / `DependentInfos` 归并为“可选辅助元数据”组；
   - 明确三档布局切换条件；
   - 预计：2–3 人天

2. `JSHClass` 创建与初始化路径改造
   - 在对象创建和初始化的入口统一收敛到“稳定骨架 + 可选辅助信息”两层；
   - 按 JIT 能力状态选择是否提前分配或延迟创建；
   - 预计：4–6 人天

3. side table / lazy access 接入
   - 把 `EnumCache` 与 `DependentInfos` 改为按需访问；
   - 对 `ProtoChange*` 做壳层兼容，保证原型链更新时可回退到旧路径；
   - 预计：4–7 人天

4. 验证与回归
   - 验证低档机无 JIT 路径下对象收缩是否稳定；
   - 检查 heap snapshot、GC 行为、枚举与原型修改场景是否兼容；
   - 预计：2–3 人天

### 4.2 总体估算

- 设计与接入：约 1 人周
- lazy metadata / side table 改造：约 1–1.5 人周
- 回归验证：约 0.5 人周

综合可估算为：**约 2–3 人周**。

## 结论

这条优化路径的核心，不是简单删减一个字段，而是把 `JSHClass` 的辅助元数据按 JIT 能力与部署环境拆成三档：

- 低档机 / 无 JIT：只保留稳定骨架，辅助元数据外迁到 side table；
- 中档机 / 轻量 JIT：保留最小内联布局，按需补齐可选字段；
- 高档机 / 完整 JIT：保留完整能力，但仍通过 lazy 方式避免对象常驻过大的内联指针阵列。

从结果看，这条路径更像是一次“对象布局分档收敛”的设计优化，而不是一处局部微调。它直接对准 `JSHClass` 的固定描述符成本，并且与当前运行时的 JIT 分档能力具备天然匹配关系。
