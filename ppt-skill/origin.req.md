任务一：
https://github.com/ningzimu/image-to-editable-ppt-skill 该skill仓库的规范很好，参考https://github.com/ningzimu/image-to-editable-ppt-skill/blob/main/AGENTS.md 整理一份本仓库的 AI 辅助编码规范，包括如下注意事项（规范是原始描述需要加工整理一下）：
1、每次调研任务，都基于原始需求req.spec.md先生成plan.spec.md，明确任务交付件和产物形式，然后生成report.spec.md,最后生成html 的slides，并且将html sildes加入到index.html索引中
2、注意index.html索引只增加slides内容,不允许放其他如md文件索引等非html slides形式的索引
3、本仓库任何AI改动都优先读取本规范内容，基于规范内容进行调整。
4、根据任务的内容拆分commit，最后完成多个任务经过验证后一起push到远程才算结束任务
5、如果调研内容经过修正，主要不要保留任何过程性的内容，二次修改需要针对过程性内容做一轮额外审查。过程性内容是指，任何第一个人看到这个报告或者html slides的人，都不应该能明显感觉，该内容是出过错或信息不足，而后经过修正，每个人看到这个内容就应该是最终状态只关注内容本身，不关注其他对本内容主题无关的内容。

任务二：
  针对小白总结一下这个skill从安装使用全部的流程以及注意事项 https://github.com/ningzimu/image-to-editable-ppt-skill   

  总体分两部分：

  1、各工具下安装和使用命令及步骤
  2、该技能能够做到的效果
  3、注意事项（尤其注意，在gpt5.5表现较好，但是比较费token。中间一步时根据源图+标注信息输出json，这一步应为deepseek不支持识别图片，因此会在直接编造不用尝试，等deepseek支持识图可能会好）

1、先总结写入报告md，然后再制作html slides 加入index.html  提交推送。
2、为本仓库建立agent.md  




