# ArkTS 与仓颉同功能最小应用 CodeSize 对比 · 需求

[原始需求] 总结 ArkTS 与仓颉实现相同最小页面功能时的 CodeSize 对比；区分 HAP 部署成本、应用私有代码、公共运行时与框架固定成本；排除语言启动/注册固定开销；确认仓颉 LTO 配置；分析仓颉 UI 宏展开生成的公共代码及其 CodeSize 占比。

[功能范围]
- 初始显示 `Hello World`
- 页面出现时更新为 `Ready`
- 点击后更新为 `Clicked`
- `Row + Text` 页面结构
- 50 字号、Bold、100% 宽高

[产物]
- `report.spec.md` — 构建口径、实测数据、差分计算、宏展开归因与证据边界
- `arkts-cangjie-codesize-slides.html` — 交互式演示
