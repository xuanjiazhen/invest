计划进行仓颉C-FFI内存安全相关的分析并寻找更安全的C-FFI的机会

当前需要先对仓颉-CFFI的现状进行分析，结合仓颉语言的CFFI能力，全面梳理，可能存在内存安全的问题有哪些？总结并以网页ppt的方式呈现

包括但不局限于下面几个方面：
1、互操作边界类型映射错误，导致ABI不一致
2、指针安全，C侧指针跨越边界，分配释放管理遗漏导致空指针、内存泄漏等等
3、仓颉侧通过acquireRelease等接口暴露仓颉堆上内存到C侧
4、仓颉通过inout暴露栈上内存到C侧

结合上面内存以及C语言常见安全问题，以及竞品go、swift、rust等C互操作安全问题和措施、完整穷举遍历仓颉语言的C互操作可能存在哪些类别的安全问题，每一类问题，都结合不同的案例进行说明

参考资料：
仓颉文档：https://cangjie-lang.cn/docs?url=https%3A%2F%2Fcj-docs.gitcode.com%2Fzh%2F1.1.3%2Fdev-guide%2Fsource_zh_cn%2FFFI%2Fcangjie-c.html

API： https://cangjie-lang.cn/docs?url=https%3A%2F%2Fcj-docs.gitcode.com%2Fzh%2F1.1.3%2Flibs%2Fstd%2Fcore%2Fcore_package_api%2Fcore_package_funcs.html%23func-acquirearrayrawdatat-arrayt-where-t-ctype


一、竞品校验存在问题：
1 编译期类型校验，Rust#[repr(C)]和仓颉@C有什么区别？
2 指针生命周期，仓颉的CPointer与Swift UnsafePointer有啥区别，为什么它就更安全？
3 空指针安全，仓颉语言也提供了Option，但和Swift Optional、Rust Option等类似能直接出现在互操作边界上面吗？
4 堆内存暴露，仓颉acquire相关也必须出现在unsafe块中，谁更安全了吗？
5、栈内存暴露给出示例来对比
6、自动头文件，仓颉有社区cjbind方案

竞品校验客观一些，如果大家竞品能力都不足，应当评价为同一等级，不要用红色绿色区分开

二、仅分析仓颉调用C的方式，不考虑C通过cangjie.h接口调用的方式。

三、示例代码要可运行，部分API实际不存在（本机有现成的cangjie sdk）
