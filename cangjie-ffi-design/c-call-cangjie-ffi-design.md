
# C调用仓颉设计方案

计划基于当前仓颉C互操作设计，扩充支持从C调用仓颉的能力。

当前运行时已在cangjie.h中提供部分接口，用于在C侧拉起仓颉运行时并调用仓颉侧内容。

问题：
Cangjie.h 中接口太过底层，用户使用不够方便，且用户需要关注的额外信息非常多，跟现有的C互操作机制完全是另外两套没有任何关联。

计划：
1、调研Swift和C的互操作能力，重点调研C调Swift同等功能；调研go和C的互操作能力，重点调研C调用go的能力。注意：Cangjie.h中提供的接口是把一些过程暴露出来，在其他语言互操作中，这些步骤可能隐藏在用户的某些操作中并不对用户暴露。这些隐藏的内容需要重点调研。

2、基于当前仓颉C互操作设计，准备一份提案，基于@C修饰的函数和foreign 函数，并且编译时自动生成头文件，并且扩展不只允许CType，还允许部分仓颉特有类型出现在CFunc中，同时将运行时中接口中描述的加载过程隐藏避免暴露给用户。

提案的格式可以参考swift等其他语言的社区提案：https://github.com/swiftlang/swift-evolution/blob/main/proposals/0495-cdecl.md


下面是参考文档：


仓颉C互操作文档指南：
https://cangjie-lang.cn/docs?url=https%3A%2F%2Fcj-docs.gitcode.com%2Fzh%2F1.1.3%2Fdev-guide%2Fsource_zh_cn%2FFFI%2Fcangjie-c.html

仓颉C互操作SPEC设计：

https://cangjie-lang.cn/docs?url=%2F0.53.18%2FSpec%2Fsource_zh_cn%2FChapter_13_Interop%28zh%29.html

仓颉标准库：
D:\docker\code\cangjie_runtime\stdlib\libs\std

仓颉运行时：
D:\docker\code\cangjie_runtime\runtime\src

仓颉运行时对外暴露的C调用仓颉接口：

D:\docker\code\cangjie_runtime\runtime\output\common\linux_release_x86_64\include\Cangjie.h
