# 详细方案归档（标记可行、待深入细化）

本目录归档「标记可行、待深入细化」的方案，按**背景 / 需求 / 方案设计**三方面组织，方案设计遵循《架构特性设计模板》。正式文档独立成篇，多角色评审记录单独保存在各方案子文件夹的 `04-review-log.md`，不混入正式方案内容。

| 方案 | 子文件夹 | 背景 | 需求 | 方案设计 | 插桩 patch |
|---|---|---|---|---|---|
| JSHClass 64B AuxData Sidecar | `jshclass-auxdata-sidecar/` | 01-背景.md | 02-需求.md | 03-方案设计.md | — |
| ProfileTypeInfoCell 编译期裁槽 | `profile-type-info-cell-jitfree/` | 01-背景.md | 02-需求.md | 03-方案设计.md | — |
| Native Interop 闭包惰性原型绑定 | `native-interop-lazy-binding/` | 01-背景.md | 02-需求.md | 03-方案设计.md | 05-插桩patch.md |
| 对象字面量外置 Backing COW | `constantpool-shared-literal/` | 01-背景.md | 02-需求.md | 03-方案设计.md | 05-插桩patch.md |
| LayoutInfo 属性描述槽压缩 | `layoutinfo-attr-packing/` | 01-背景.md | 02-需求.md | 03-方案设计.md | — |

## 归档结构说明

- **01-背景.md**：理解方案所需的背景知识、现有实现、数据事实；
- **02-需求.md**：方案收益、工作量、风险、验收门槛、依赖；
- **03-方案设计.md**：按架构特性设计模板归档的细化设计；
- **04-review-log.md**（各方案子文件夹内）：多角色评审记录与闭环意见，独立保存；
- **05-插桩patch.md**（部分方案）：前置量化/验证所需的打桩改动设计（含打点位置、输出格式与验证思路），供人工取用实施。