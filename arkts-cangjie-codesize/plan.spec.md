# ArkTS 与仓颉同功能最小应用 CodeSize 对比 · 执行计划

[数据采集]
1. 固定 SDK、ABI、Release、优化等级、资源、压缩、strip 与依赖口径。
2. 构建具有相同可观察行为的 ArkTS 与仓颉功能应用。
3. 记录 HAP 压缩尺寸与解压尺寸，单列公共动态库固定成本。
4. 构建保留应用壳的空页面基线，以功能产物减基线产物计算应用私有净业务增量。
5. 在仓颉 `cjpm.toml` 中配置 Full LTO，以实际配置和三轮 clean Release 产物验证尺寸与哈希稳定性。
6. 使用 `--debug-macro` 导出 `.macrocall`，记录 `@Entry/@Component/@State` 展开内容。
7. 构建空 Row、静态 Text、未使用 State、使用 State、生命周期更新、点击更新六个分层变体，按 strip ELF 差分归因宏公共代码。

[计算口径]
- 部署成本：最终 unsigned HAP。
- 应用私有代码：ArkTS `modules.abc` 对仓颉 strip 后应用 `.so`。
- 净业务代码：功能应用私有代码减空页面应用私有代码。
- 劣化率：`(仓颉 - ArkTS) / ArkTS × 100%`。
- 宏公共占比：未使用 State 变体相对静态 Text 变体的增量 / 最终功能页相对空 Row 壳的净增量。

[交付件]
- `report.spec.md`
- `arkts-cangjie-codesize-slides.html`
