# 仓颉调用 C 的内存安全调研计划

## 目标

以仓颉 1.1.3 文档与本机 Cangjie Compiler 1.1.0-beta.10 为基准，分析“仓颉调用 C”方向的 ABI、指针、所有权、堆数组借用、`inout` 栈地址、并发与工具链风险，并形成可验证的结论。

## 范围

- 包含：`foreign func`、`CFunc`、`CPointer<T>`、`CString`、`VArray`、`@C struct`、`@CallingConv`、`acquireArrayRawData`/`releaseArrayRawData`、`inout`。
- 不包含：C 通过 `Cangjie.h` 或运行时接口调用仓颉、仓颉函数导出给 C 的机制设计。
- 竞品：Rust、Swift、Go；只比较原始 C 互操作边界，不把安全封装能力等同于边界本身的自动安全。

## 交付件

1. `req.spec.md`：保留原始任务与评审意见。
2. `plan.spec.md`：范围、证据与验证标准。
3. `report.spec.md`：风险分类、真实 API、可运行案例、竞品对照及建议。
4. `cangjie-cffi-memory-safety-slides.html`：16 页交互式网页演示，以风险全景为主线，竞品校验作为辅助章节。
5. `index.html`：继续仅索引 slides HTML。

## 证据与验证

- 以 `cangjie_docs` 的 1.1 文档为 API 与语义依据。
- 使用 SDK 自带 `envsetup.bat` 等价环境：`CANGJIE_HOME`、runtime/bin/tools PATH。
- 用 `clang` 构建 C DLL，用 `cjc` 编译链接仓颉调用端并运行。
- 所有作为“可运行”的仓颉片段必须来自同一条已通过的 E2E 链路。
- 竞品比较采用中性描述，明确共同局限与差异，不使用红绿优劣编码。

## 验收标准

- 报告和 slides 明确只覆盖仓颉调用 C。
- 回答六项竞品质疑：布局校验、指针生命周期、可空表达、unsafe、栈地址、头文件/绑定生成。
- 不出现不存在的 `acquireRawData`/`release` 等 API；数组借用使用 handle 的 `.pointer` 并成对释放。
- `inout` 示例展示“仅调用期间有效”。
- HTML 可加载、16 页完整、键盘与按钮翻页可用、无外部脚本依赖；主体内容完整覆盖风险分类、案例、已有防线、剩余缺口和增强路线。
