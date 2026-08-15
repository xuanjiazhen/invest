# 需求（Requirement）：应用侧内存优化统一清单（汇总稿）

每项改造的**端到端开发者指导**（识别 → 风险评估 → 改造方案 → 验证，含可交给 AI agent 的执行规程）见 `02-改造指导.md`。

本文件统一汇总**所有应用侧可行的内存改造**（原 02 惰性导入、原 03 代码坏味道、native interop 应用侧配套、字符串大串治理），框架侧（ArkUI stateMgmt 等）改动不在范围内。每项给出效果验证方法；需要 VM 配合打桩的，链接对应 patch。

## 改造项总览（按 Top13 实测收益排序）

| # | 改造项 | 存量口径（Top13） | 验证方法 |
|---|---|---|---|
| A1 | native 类注册去重（同一类重复 `napi_define_class`） | W-sys 13.39 MiB 重复拷贝 + kuaishou 216 类 ×18 份 | 改造前后 heapsnapshot 对比 `prototype` 拷贝数（`scripts/measure_lazy_binding_targets.py`、`scripts/class_copy_census.py`） |
| A2 | 系统模块（`@ohos.*`）惰性导入：静态 import → 自替换 getter | 上界 13.4 MiB（未使用模块的 prototype 闭包不驻留） | 同上 + 冷启动回归；期望值按 VM 侧 `detailed-proposals/native-interop-lazy-binding/05-插桩patch.md` 的 probe 数据折算 |
| A3 | 逐实例方法绑定提升为 prototype 共享（Bucket D，1.39 MiB） | 220,069 个非 prototype 持有闭包中同 hclass 冗余部分 | `scripts/detect_native_interop_dup.py` 对比冗余桶 |
| A4 | dynamic-key 场景改用 Map/Set（避免 JSHClass 退化为 dictionary） | ArkInternalDict 21,268 个 = 32.19 MiB（可回收量取决于业务定位） | 快照 `tagged_dictionary` 数量/字节对比；入口埋点统计 dict 模式触发（可选 VM 埋点：`TransitionToDictionary` 计数） |
| A5 | 响应式装饰器精简：非 UI 绑定状态不用 `@State/@Prop/@Link` | PropertyBox 97,568（1.49 MiB）+ get/set 对 13,651（1.87 MiB）+ WeakRef 57,288（2.19 MiB）+ 依赖记录，合计 ~20 MiB 中可精简部分 | 快照 `property_box`/`cell_record`/`js_weak_ref` 节点数对比；UI 回归 |
| A6 | 大字符串（>1K，数据 32.63 MiB）归因与缓存治理 | pinduoduo/jingdong/gaodeditu 等集中在少数模块 buffer | 快照 >1K string 按持有者归因（`evidence/top13-string-array-census.json` 已有持有方分布）；改造后对比 |

## 各项要点

### A1 注册去重
缺陷模式与修复写法见 `../../lazy-binding-app-side-guide.md` §2（改造前/后代码）；逐应用清单见同文件 §4（13 app 实测，精确到文件）。纯应用改动，无 VM 依赖。

### A2 惰性导入
适用判据、自替换 getter 模板、反模式见 `../../lazy-binding-app-side-guide.md` §3。与 VM 侧惰性绑定方案针对同一存量，**收益不可叠加**；若 VM 侧方案落地则本项自动覆盖，无需应用改造。

### A4 dictionary 预防
触发路径：动态增删 key → JSHClass 退化 → 21,268 个平均 1,587 B 的字典对象。业务侧把 dynamic-key 容器换 Map/Set 后，对应对象回到 fast mode。VM 侧（开放寻址等）保留在 `pending-review/`，不在本清单。

### A5 响应式精简
只动应用代码：非 UI 绑定的中间状态用普通类字段。框架侧（stateMgmt.js 对象分配策略）不做修改。

## 验证总方法（所有改造项通用）

1. 同设备、同版本、同 workload，改造前后各采 ≥5 份 rawheap 快照（hidumper 标准 procedure）；
2. 用本目录 `scripts/` 对应脚本对比目标节点（拷贝数/闭包数/字典字节/装饰器对象数），PSS 中位数不得回退；
3. 冷启动 P50/P95 与主流程回归通过（A2 首次访问引入加载延迟，需按模块实测）。

## 关联与依赖

- A1/A2/A3 与 `detailed-proposals/native-interop-lazy-binding/`（VM 侧）同存量，收益不叠加；
- A6 与 `feasible-proposals/04-string-optimization/` 互补（VM 管短串去重，应用管长串缓存）；
- 无框架侧改动依赖。
