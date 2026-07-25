# NapiDefineClass metadata 内存调研 · 需求

[原始需求] 通过内存 perf 图发现 NapiDefineClass 注册 class 时产生显著 metadata 分配——单个 class 从几十 KB 到 2.4 MB 不等。需要调研 metadata 的具体构成、对比业界竞品（V8 / JSC / Hermes）的同类开销。

[产物]
- report.spec.md — 事实性调研报告
- *-slides.html — 交互式演示

[来源]
- OpenHarmony 源码: arkcompiler/ets_runtime, foundation/arkui/napi
- V8 源码: src/objects/map.h, src/execution/isolate.h
- JSC 源码: runtime/Structure.h
- Hermes 源码: include/hermes/VM/HiddenClass.h
