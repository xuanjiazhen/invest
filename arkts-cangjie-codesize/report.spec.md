# ArkTS 与仓颉同功能最小应用 CodeSize 对比报告

## 1. 对比对象

ArkTS 与仓颉页面均包含一个 `message` 状态，初值为 `Hello World`；页面出现时赋值为 `Ready`；点击文本时赋值为 `Clicked`。两侧均使用 `Row + Text`，字号为 50、字重为 Bold、容器宽高为 100%。ArkTS 源码位于 `team_interop/analysis/minimal-page-codesize/arkts-minimal/entry/src/main/ets/pages/Index.ets:1-22`；仓颉源码位于 `team_interop/analysis/minimal-page-codesize/cangjie-minimal/entry/src/main/cangjie/index.cj:18-40`。

## 2. 构建口径

| 项目 | 配置 |
|---|---|
| SDK | OpenHarmony 6.0.2(22) compatibility SDK |
| ABI | `x86_64-linux-ohos` |
| 模式 | Release |
| 仓颉选项 | `--fast-math -O2 -s -Woff all -Won apilevel-check` |
| 仓颉 LTO | `lto = "full"` |
| 重复构建 | 3 次 clean Release |
| ArkTS 私有代码产物 | `modules.abc` |
| 仓颉私有代码产物 | strip 后 `libohos_app_cangjie_entry.so` |

仓颉 Full LTO 配置位于 `team_interop/analysis/minimal-page-codesize-lto-spike/cangjie-feature/entry/cjpm.toml:14-22`，其中 `[profile.build]` 使用 `lto = "full"`。三轮 clean Release 的四个私有代码产物尺寸和 SHA-256 保持一致；HAP 尺寸保持一致，HAP SHA-256 随打包元数据变化，记录位于 `team_interop/analysis/minimal-page-codesize-lto-spike/measurement.json:31-37`。

## 3. 三种 CodeSize 口径

### 3.1 HAP 部署成本

| 产物 | ArkTS | 仓颉 | 仓颉/ArkTS | 劣化率 |
|---|---:|---:|---:|---:|
| unsigned HAP | 117,822 B | 23,209,991 B | 196.99× | 19,599.20% |
| HAP 解压总量 | 116,382 B | 23,169,027 B | 199.08× | 19,807.74% |

仓颉 HAP 中公共仓颉运行时、标准库、Ability、CangjieUI、互操作库及其他平台动态库合计 22,979,224 B，占仓颉 HAP 的 99.01%。该口径记录安装和下载交付物尺寸，不用于净业务代码劣化率。

### 3.2 应用私有代码，不扣除应用壳

| 产物 | ArkTS | 仓颉 | 绝对增量 | 仓颉/ArkTS | 劣化率 |
|---|---:|---:|---:|---:|---:|
| 应用私有可执行交付物 | 9,304 B | 83,120 B | 73,816 B | 8.93× | 793.38% |

该口径排除了 HAP 中独立公共动态库，但仓颉应用 `.so` 仍包含应用壳、语言启动与注册、空页面 UI 骨架和宏生成代码。

### 3.3 排除应用壳、启动与注册固定开销

空页面基线保留相同模块、Ability、应用入口、`@Entry/@Component` 和空 `Row`。仓颉空页面源码位于 `team_interop/analysis/minimal-page-codesize-lto-spike/cangjie-baseline/entry/src/main/cangjie/index.cj:13-22`。差分结果记录于 `team_interop/analysis/minimal-page-codesize-lto-spike/measurement.json:18-29`。

| 项目 | 功能产物 | 空页面基线 | 净业务增量 |
|---|---:|---:|---:|
| ArkTS `modules.abc` | 9,304 B | 7,728 B | 1,576 B |
| 仓颉 strip `.so`，Full LTO | 83,120 B | 71,184 B | 11,936 B |

计算：

- 仓颉/ArkTS：`11,936 / 1,576 = 7.5736×`
- 绝对净增量：`11,936 - 1,576 = 10,360 B`
- 劣化率：`(11,936 - 1,576) / 1,576 × 100% = 657.36%`

## 4. LTO 状态

无 LTO 配置为 `lto = ""`，Full LTO 配置为 `lto = "full"`；两种配置均使用相同 Release 选项。功能页 strip `.so` 在本次样本中均为 83,120 B，LTO 开关对应的文件 SHA-256 不同。尺寸变化为 0 B，变化率为 0%。

| 仓颉功能页 | strip `.so` | SHA-256 |
|---|---:|---|
| 无 LTO | 83,120 B | `68caa2df7da8c4c4ac61db0e0f09b2db677ba54549497a442a0a7a29a2d07279` |
| Full LTO | 83,120 B | `e7d5870bde4c660823c1fd10067b0d0c5ff708b8670f13fb0b12e9d63ab54d88` |

无 LTO 配置位于 `team_interop/analysis/minimal-page-codesize/cangjie-minimal/entry/cjpm.toml:14-22`；Full LTO 配置位于 `team_interop/analysis/minimal-page-codesize-lto-spike/cangjie-feature/entry/cjpm.toml:14-22`。

## 5. 仓颉 UI 宏展开

编译器 `--debug-macro` 输出的 `.macrocall` 显示，空页面的 `@Entry/@Component` 生成以下应用壳代码：

- `EntryView <: CustomView` 与 `observeComponentCreation`；
- 构造器、`SubscriberManager.add`、`registerSelf` 和父子 View 注册；
- `aboutToBeDeleted`、`updateWithValueParams`、`rerender`、依赖清理和强制刷新；
- `appEntry0`、`loadNativeView` 与 `CJEntry.registerEntry`。

对应展开内容位于 `team_interop/analysis/minimal-page-codesize-macro-spike/cangjie-baseline-debug-macro/entry/src/main/cangjie/index.cj.macrocall:13-50`。

功能页的 `@State message` 生成 `ObservedProperty<String>` backing field、getter/setter、构造器状态参数、`subscribeEx`、`unsubscribeEx`、带状态参数的 `updateWithValueParams` 和状态依赖清理。对应内容位于 `team_interop/analysis/minimal-page-codesize-macro-spike/cangjie-feature-debug-macro/entry/src/main/cangjie/index.cj.macrocall:18-83`。

## 6. UI 宏公共代码占比

分层变体均采用 Full LTO Release，并测量 strip 后应用私有 `.so`。数据记录于 `team_interop/analysis/minimal-page-codesize-macro-spike/macro-measurement.json:2-27`。

| 分层变体 | 私有 `.so` | 相对上一层增量 |
|---|---:|---:|
| 空 Row 应用壳 | 71,216 B | — |
| Row + Text + 样式 | 75,920 B | 4,704 B |
| 静态页面 + 未使用 `@State message` | 82,128 B | 6,208 B |
| 状态用于 Text | 82,224 B | 96 B |
| 生命周期状态更新 | 82,336 B | 112 B |
| 点击状态更新，完整功能页 | 83,152 B | 816 B |

完整功能页相对空 Row 应用壳的净增量为 11,936 B，分解如下：

| 组成 | CodeSize | 净增量占比 |
|---|---:|---:|
| 页面组件和样式 | 4,704 B | 39.41% |
| 一个 `@State<String>` 触发的公共状态管理骨架 | 6,208 B | 52.01% |
| 状态读取、生命周期更新和点击更新 | 1,024 B | 8.58% |
| 合计 | 11,936 B | 100.00% |

从静态 Text 页面到完整状态页面的增量为 7,232 B，其中公共状态管理骨架占 `6,208 / 7,232 = 85.84%`。

## 7. ELF section 交叉数据

| 变体 | `.text` | `.cjmetadata` |
|---|---:|---:|
| 空 Row 应用壳 | 4,831 B | 19,448 B |
| Row + Text + 样式 | 5,775 B | 20,008 B |
| 未使用 State | 6,463 B | 22,072 B |
| 完整功能页 | 7,695 B | 23,064 B |

`@State` 变体同时增加 `.text`、`.cjmetadata`、动态符号、重定位和异常展开数据。6,208 B 为 strip ELF 文件级差分，不等同于 `.text` 单段增量。

## 8. 数据边界

1. ArkTS ABC 与仓颉 ELF 属于不同可执行交付格式；657.36% 表示应用私有净业务交付尺寸差异，不表示逐指令编译效率。
2. 6,208 B 来自一个 `@State<String>` 的分层差分，不是所有状态类型、组件数量或大型应用的固定常数。
3. Full LTO 会内联、消除和删除函数；strip 后没有完整本地符号。宏生成方法没有逐函数机器码精确归属，CodeSize 使用分层构建差分归因。
4. 空应用壳含 `@Entry/@Component` 生成的入口、注册和 View 生命周期骨架；这些字节已由空页面基线排除。
5. HAP 数据包含公共动态库固定成本，仅表示部署交付尺寸。
