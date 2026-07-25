任务一：
https://github.com/ningzimu/image-to-editable-ppt-skill 该skill仓库的规范很好，参考https://github.com/ningzimu/image-to-editable-ppt-skill/blob/main/AGENTS.md 整理一份本仓库的 AI 辅助编码规范，包括如下注意事项（规范是原始描述需要加工整理一下）：
1、每次调研任务，都基于原始需求req.spec.md先生成plan.spec.md，明确任务交付件和产物形式，然后生成report.spec.md,最后生成html 的slides，并且将html sildes加入到index.html索引中
2、注意index.html索引只增加slides内容,不允许放其他如md文件索引等非html slides形式的索引
3、本仓库任何AI改动都优先读取本规范内容，基于规范内容进行调整。
4、根据任务的内容拆分commit，最后完成多个任务经过验证后一起push到远程才算结束任务
5、如果调研内容经过修正，主要不要保留任何过程性的内容，二次修改需要针对过程性内容做一轮额外审查。过程性内容是指，任何第一个人看到这个报告或者html slides的人，都不应该能明显感觉，该内容是出过错或信息不足，而后经过修正，每个人看到这个内容就应该是最终状态只关注内容本身，不关注其他对本内容主题无关的内容。
6、本仓库仅保留必要的md以及html slides等相关文件，其他过程性的内容，如果不是服务于上述内容，则不应该添加到本仓库中。
7、每一个任务一旦存在原始需求的内容，那每次提交到远程前，都必须要确保所有规范内容生成部署，提交前不允许存在未完成的任务内容。完成任务是指，根据规范定的各个阶段产物都已经完成。

任务二：
  针对小白总结一下这个skill从安装使用全部的流程以及注意事项 https://github.com/ningzimu/image-to-editable-ppt-skill   

  总体分两部分：

  1、各工具下安装和使用命令及步骤
  2、该技能能够做到的效果
  3、注意事项（尤其注意，在gpt5.5表现较好，但是比较费token。中间一步时根据源图+标注信息输出json，这一步应为deepseek不支持识别图片，因此会在直接编造不用尝试，等deepseek支持识图可能会好）

1、先总结写入报告md，然后再制作html slides 加入index.html  提交推送。
2、为本仓库建立agent.md  


任务三：
1、根据最新的规范整理一下仓库中的所有内容，该删除的删除，该改名字的改名字，该规范化内容的规范化内容，该补充html slides的补充对应的网页生成。但不要调整已经做好的html slides和index.html的内容。只是根据规范做一个重构。
2、简要基于仓库内容补充一下readme，本仓库用来使用各种AI辅助进行调研总结任务以及各种适用于AI尝试的想法。但readme中不要出现任何具体调研内容，期望后续持续更新调研内容，而readme不需要随着调研内容增加而每次做适配