# 不可行方案（事实被源码推翻 / 推导被否决）

下列方案**不建议继续投入**：要么事实基础与源码不符，要么收益推导被复核意见明确否决。

## 1. ConstantPool 稀疏化（250–280 MiB）

- 出处：已清理的 ConstantPool 稀疏化提案、`top13-heap-optimization-opportunities.md:18-36`
- 否决依据（ConstantPool 稀疏化复核意见，复核通过）：
  - 「可见非 Hole 槽约 4.5% → 稳态容量 10%」推导不成立；连续数组占用取决于**最高访问 index**，不取决于已填槽数；
  - 生成代码（`circuit_builder.cpp:974-1005`、`stub_builder-inl.h:3176-3179`）直接按 index 做数组寻址，无边界检查，初始缩容到 64 会造成越界——不是 `GetObjectFromCache` 加一次检查的局部改动；
  - 方案 B 用 `NumberDictionary`，10% 填充时已达 dense 数组的 49.2%，25% 时 150–196%，「每条 24B」低估真实容器成本；
  - 方案 D 的 dense 合并只省对象头 + 尾部槽，上界约 0.34 MiB。
- 结论：A/B 从「P0」降为「需运行时访问分布证明的架构实验」；250–280 MiB 不得发布。

## 2. Method 瘦身（裁剪 machine_code/baseline_code，64→40–48 B）

- 出处：`top13-heap-optimization-opportunities.md:104-111`
- 否决依据：`method.h:485-499` 的字段为 ConstantPool/CallField/NativePointerOrBytecodeArray/CodeEntryOrLiteral/LiteralInfo/ExtraLiteralInfo/ExpectedPropertyCount，**不含** machine_code / baseline_code（`Select-String -Path method.h -Pattern "MachineCode|BaselineCode"` 匹配数为 0）。
- 结论：JIT 字段在 `JSFunction` 里（`js_function.h`），不在 `Method` 里；「Method 瘦身 25–37 MiB」的前提不成立。

## 3. FunctionTemplate 瘦身（裁剪 JIT/调试字段）

- 出处：`top13-heap-optimization-opportunities.md:167-175`
- 否决依据：`js_function.h:732-758` 的 `FunctionTemplate` 仅 Method/Module/RawProfileTypeInfo/Length 四个字段，无 JIT/调试字段可裁剪。
- 结论：「40B 中与 JIT/调试相关部分裁剪」无事实依据。

## 4. ProfileTypeInfoCell JIT-off 裁剪（28.5 MiB）

- 出处：`top13-heap-optimization-opportunities.md:179-196`
- 否决依据：cell_0 由**解释器 IC 反馈路径**分配——`interpreter-inl.cpp:1046-1063` 的 `UpdateProfileTypeInfoCellToFunction` 在 profile slot 未建立时 `NewProfileTypeInfoCell`，与 JIT 无关；函数创建时默认 `RawProfileTypeInfo = EmptyProfileTypeInfoCell` 单例（`js_function.cpp:112`），非空 cell 都是运行时反馈产生的。
- 结论：「JIT 未启用时该 32B 对象无实际用途」不成立；「无机器码 ⇒ 反馈对象无用途」是错误推理。方案 C（共享 cell_0 单例）也与 Empty 单例语义冲突（Empty 不能 transition 到 cell_1）。

- 评审结论（人工提出）：ProfileTypeInfoCell 的「JIT-off 裁剪」与「共享 cell_0 单例」已被否决，但可另行审视是否存在其他优化空间（如按需/阈值分配）；toJSON 闭包与冗余函数绑定的优化空间已单列（cell 槽位裁剪与按需分配已合并为两阶段方案 `../detailed-proposals/profile-type-info-cell-jitfree/`）。


## 5. JIT 分档布局（56/88B 双档切换）

- 出处：已清理的 JIT 分档布局提案两篇
- 否决依据：
  - 把 ProtoChange/EnumCache 混为「JIT 辅助元数据」——它们服务原型变更与枚举语义，`MarkProtoChanged` 在 `js_hclass-inl.h:380-399` 读 EnumCache/Marker，无 JIT 仍使用；
  - 同一 JSType 在运行期用 56/88B 会使 visitor、compiled load、snapshot、factory 失配；设备档位切换会形成混合堆；
  - 关闭 JIT 不等于关闭 IC、AOT、for-in 或 prototype mutation。
- 结论：运行时物理布局分档不成立；2–3 人周严重低估。

## 6. JSFunction 辅助对象 side-table（预分配对象外迁）

- 出处：已清理的 JSFunction 辅助对象外迁提案
- 否决依据：`RawProfileTypeInfo`/`MachineCode`/`BaselineCode`/`Module` 是 `JSFunction` 对象内的 **tagged 槽**（初始化为 Undefined/单例），不等于「创建时为每槽分配外部对象」；`Module` 是模块/脚本归属，不是 JIT-only 字段。
- 结论：把槽位误读为预分配对象；「50% 未 JIT ⇒ 平均节省 16–32B」不成立。

## 7. 内建/常用函数 Flyweight

- 出处：已清理的函数 Flyweight 提案
- 否决依据：函数对象的 `===`、WeakMap/WeakRef、`Object.getOwnPropertyDescriptor`、bind、proxy、堆快照都暴露对象 identity；不存在「首次任意观察时可无缝替换成共享模板」的代理引用。
- 结论：只能收窄为共享 Method/template/HClass（源码已有），不能共享 JSFunction 对象本体。

## 8. JSFunction 代码槽 JIT-free 编译期移除（31.14/43.20 MiB）

- 出处：已清理的 `feasible-proposals/07-jsfunction-code-slot-removal/`
- 否决依据（人工审视，2026-08-15）：**JSFunction 相关布局的任何变化都被视为不兼容**——部分三方应用直接基于函数对象指针按固定偏移拷贝内存布局，一旦修改，应用无法工作。该约束同时封堵运行时双布局与编译期单布局两条路线。
- 结论：JSFunction 112 B 布局冻结为硬约束，记入 `CONTEXT.md`；同档位的 cell 裁剪（ProfileTypeInfoCell）与 cell 惰性分配（feasible 15）不受影响（不同对象）。

## 9. AccessorData 内联（5.57 MiB）

- 出处：已清理的 `feasible-proposals/08-accessordata-inline/`
- 否决依据（人工审视）：收益和付出不成正比（descriptor 扩容连锁 Lookup 性能与 IC 语义验证）。

## 10. TaggedArray (Elements/Properties) GC 后 trim（上界 41.81 MiB）

- 出处：已清理的 `feasible-proposals/09-tagged-array-trim/`
- 否决依据（人工审视）：GC 调整复杂，收益和付出不成正比，且影响范围大。

## 11. 模块元数据压缩（30–45 MiB）

- 出处：已清理的 `feasible-proposals/10-module-metadata-compression/`
- 否决依据（人工审视）：收益和付出不成正比，影响兼容性（binding 记录结构变化触及模块链接语义）。

## 12. ClassLiteral 惰性驻留（2–4 MiB）

- 出处：已清理的 `feasible-proposals/12-classliteral-lazy/`
- 否决依据（人工审视）：付出和收益不成正比。

## 13. 编译器侧 method_idx_size 缩减（~50 MiB，带前提）

- 出处：已清理的 `feasible-proposals/13-compiler-method-idx-reduction/`
- 否决依据（人工审视）：存在反射路径使 DCE 不可靠，编译器已做部分 DCE，且对运行时内存贡献不明。

## 14. 共享单例 HClass（函数类）

- 出处：早期低置信清单 §1
- 否决依据（人工审视）：未证明现有路径存在可消除的重复；GlobalEnv 预构建函数类已复用，shared/local 混用违反堆归属。
