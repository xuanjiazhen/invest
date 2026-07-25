# NapiDefineClass metadata 内存调研 · 执行计划

[已实施]
1. 源码回溯 NapiDefineClass 完整调用链 → HClass / JSFunction 创建 → SemiSpace 分配
2. 定位 metadata 构成：JSHClass (~128B)、IC feedback vector (1-8KB)、SemiSpace region (256KB)
3. 对照 V8 / JSC / Hermes 同级结构逐项对比

[交付件]
- report.spec.md — 事实陈述：调用链 + 结构对比 + 常量引用
- slides.html — 基于报告的交互式演示（≤10 页）
