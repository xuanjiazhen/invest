
一：鸿蒙性能调优工具简介


CodeLinter提供静态代码扫描能力，通过性能规则检查代码是否存在性能问题，帮助开发者分析和修改性能问题。

[codelinter](./codelinter.png)

AppAnalyzer提供性能根因诊断能力，通过智能收集trace日志、代码调用栈、故障事件等关键数据，提取关键特征，直接追溯性能问题根源并提供页面滑动、页面转场、冷启动场景性能问题优化建议，开发者只需简单操作，就能迅速定位到问题根因，提升定位效率。

[AppAnalyzer](./AppAnalyzer.png)

DevEco Profiler提供实时监控（Realtime Monitor）能力，提供全方位的设备资源监测，覆盖系统事件、异常报告、CPU占用、内存占用、实时帧率、GPU使用率、能耗以及网络流量消耗等多个维度的数据，自顶向下逐层展开分析，并可借助DevEco Profiler跳转到代码位置，结合代码进行白盒分析，明确不合理的负载出现位置，帮助识别性能瓶颈，定界问题所在，提高解决问题的效率。
[DevEco Profiler](./profile.png)

本次重点分析codelinter相关能力GAP。

二、能力GAP总览
- 通用规则@typescript-eslint  ArkTS codelinter：√  Cangjie cjlint：√ 
- 安全规则@security ArkTS codelinter：√  Cangjie cjlint：〇 
- 性能规则@performance ArkTS codelinter：√  Cangjie cjlint：× 
- 预览规则@previewer ArkTS codelinter：√  Cangjie cjlint：× 
- 一次开发多端部署规则@cross-device-app-dev ArkTS codelinter：√  Cangjie cjlint：× 
- ArkTS代码风格规则@hw-stylistic ArkTS codelinter：√  Cangjie fmt：√
- 正确性规则@correctness ArkTS codelinter：√  Cangjie cjlint：？ 
- 兼容性规则@compatibility ArkTS codelinter：√  Cangjie cjlint：x 

三、GAP能力项详细展开


1、安全规则@security

TODO：首先需要基于链接遍历每条codelinter规则内容https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-security
其次基于cjlint手册确认是否存在对应能力项：
https://developer.huawei.com/consumer/cn/doc/cangjie-guides/cj-cjlint_manual
最后输出每一项对比差距，并补充下面问号部分


ArkTS codelinter：              Cangjie cjlint
@security/no-commented-code             ？（√还是x）
@security/no-cycle            ？（√还是x）
@security/no-unsafe-aes            ？（√还是x）
@security/no-unsafe-dh            ？（√还是x）
@security/no-unsafe-dsa            ？（√还是x）
@security/no-unsafe-dh-key            ？（√还是x）
@security/no-unsafe-dsa-key            ？（√还是x）
@security/no-unsafe-ecdsa            ？（√还是x）
@security/no-unsafe-hash            ？（√还是x）
@security/no-unsafe-mac            ？（√还是x）
@security/no-unsafe-rsa-encrypt            ？（√还是x）
@security/no-unsafe-rsa-key            ？（√还是x）
@security/no-unsafe-rsa-sign            ？（√还是x）
@security/no-unsafe-3des            ？（√还是x）
@security/specified-interface-call-chain-check            ？（√还是x）
@security/no-unsafe-kdf            ？（√还是x）
@security/no-unsafe-sm4            ？（√还是x）
@security/no-unsafe-sm2-key            ？（√还是x）
@security/no-unsafe-sm2-cipher            ？（√还是x）
@security/no-unsafe-ecdh            ？（√还是x）
@security/no-unsafe-huks            ？（√还是x）


2、性能规则@performance

TODO：参考上述处理：https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-performance

需要对比每一条仓颉是否有gap

3、预览规则@previewer

TODO：参考上述处理：https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-previewer

人工判断：Cangjie Cjlint此项基本没有

4、一次开发多端部署规则@cross-device-app-dev

TODO：参考上述处理：
https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-cross-device-app-dev

人工判断：Cangjie Cjlint此项基本没有

5、正确性规则@correctness
TODO：参考上述处理：https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-codelinter-correctness

人工判断：此类规则Cangjie Cjlint基本没有

6、兼容性规则@compatibility

TODO：参考上述处理：
https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/ide-api-compatibility-check

人工判断：仓颉基本没有。


思考&总结：性能规则当前最值得关注，
1、lint功能补齐？  
2、提取出具体规则，融入到skill中？

无论是做到lint中还是做到skill中，都需要先把具体的规则先整理出来，这些内容是不变的。
