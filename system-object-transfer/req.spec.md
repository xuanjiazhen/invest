# 仓颉与 ArkTS-Dyn 系统对象转换方案需求

## 背景

ArkTS-Dyn 与 ArkTS-Sta 交互时，一部分对象同时具备以下特征：

1. 绑定底层 C++ 对象；
2. 在两种语言侧具有不同的包装表示。

业务同时调用两侧接口时，需要保证两侧包装对象共享同一底层 C++ 对象。此类对象称为系统对象。

仓颉提供约 8k API，也允许开发者通过互操作调用尚未提供仓颉封装的 ArkTS-Dyn 接口。仓颉对象与 ArkTS-Dyn 对象之间同样需要系统对象转换能力。

## 任务

1. 参考 ArkTS 静动态系统对象转换机制，设计仓颉侧系统对象转换接口。
2. 结合仓颉语言的泛型、接口扩展等能力，减少调用负担，并尽量在编译期暴露类型错误。
3. 支持以下使用者：
   - 直接调用互操作接口并取得 ArkTS-Dyn 对象的应用开发者；
   - 对互操作结果进行自定义封装的应用开发者；
   - 为仓颉提供系统 API 封装的子系统开发者。
4. 结合当前仓颉 API、ArkTS-Dyn API 和 ArkTS 静动态系统对象清单，识别当前需要支持的仓颉系统对象。范围仅限已有接口。
5. 给出新增系统对象的扩展方法，供后续 API 持续接入。

## 交付内容

1. 背景与系统对象定义，并以图示说明同一底层 C++ 对象在仓颉和 ArkTS-Dyn 两侧的表示。
2. ArkTS 静动态系统对象机制及可复用边界。
3. 应用开发者使用转换能力的接口和示例。
4. 子系统 API 开发者及应用开发者封装系统对象的方法。
5. 当前仓颉系统对象清单、覆盖状态和依据。
6. 实际应用封装示例。
7. 设计、开发、测试工作量和排期。

## 参考材料

- ArkTS 静动态系统对象说明：<https://gitcode.com/openharmony/docs/blob/OpenHarmony_feature_sta_20260331/zh-cn/application-dev/reference/apis-arkts/js-apis-transfer.md>
- 仓颉 API 文档：<https://gitcode.com/openharmony/docs_cangjie/tree/master/zh-cn/application-dev/reference>
- 本地参考：`C:\Users\xuanj\Downloads\arkts_static_dynamic_transfer_summary.md`
