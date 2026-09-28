# 公开源码预览版状态

最后更新：2026-09-28

当前版本基于 v0.11.1，面向 macOS 单用户本地使用。

| 项目 | 状态 |
| --- | --- |
| 履历库、JD 匹配、中文草稿、编辑、导出与历史版本 | 已实现 |
| 空白初始化、独立合成 demo、Key 自行配置 | 初始化与 demo 通过；新用户 Key 配置待首次安装试用 |
| Python 与 JavaScript 离线回归 | 独立源码包 123 Python / 20 JS 通过 |
| 所有服务商与模型的真实调用 | 未全部验证 |
| 完整多经历排序与文字质量矩阵 | 待补齐 |
| 原生应用菜单、退出与首次安装人工体验 | 待完成 |
| 开源许可 | MIT，已添加 LICENSE |
| GitHub 仓库发布 | 已发布：[jkevin39/resume-produce](https://github.com/jkevin39/resume-produce)，main 分支 |

发布清单：

- [x] 使用独立源码副本，不包含旧 Git 历史、个人资料或旧验收目录。
- [x] 提供面向新用户的 README、合成 demo 和数据说明。
- [x] 对导出的源码执行离线回归与初始化检查。
- [x] 确定许可并添加 LICENSE。
- [ ] 新用户在另一台 Mac 上完成首次使用。
- [x] 发布 GitHub 仓库。

本预览版不代表所有质量 Gate 已关闭。验证结果见 [验收记录](tests/ACCEPTANCE.md)。

85 次 Python 渲染仅留两组：[可编辑 HTML](tests/artifacts/public-source-20260928/render-editable/resume.html) / [Spec](tests/artifacts/public-source-20260928/render-editable/resume-spec.json)，[正式 HTML](tests/artifacts/public-source-20260928/render-static/resume.html) / [Spec](tests/artifacts/public-source-20260928/render-static/resume-spec.json)。初始化额外验证两次首页响应，无额外留存。

## 更新记录

| 日期 | 更新 |
| --- | --- |
| 2026-09-28 | 准备公开源码包、首次使用文档、数据流说明、MIT 许可与合成演示；独立副本 123 Python / 20 JS、初始化检查通过，保留两组 HTML + Spec。GitHub 发布、另一台 Mac 首次使用及原有质量 Gate 保持开放。 |

| 2026-09-28 | 已创建公开仓库并推送首次提交 `4d6694d`，共 128 文件；另一台 Mac 首次安装及原有质量 Gate 保持开放。 |
