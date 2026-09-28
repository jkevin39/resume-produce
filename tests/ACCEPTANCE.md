# 公开源码包验收

本次检查对象为独立导出的源码目录，所有履历与 JD 均为合成内容。

2026-09-28：在独立导出的源码副本上使用 macOS / Python 3.9.6 完成验证。

| 检查 | 结果 |
| --- | --- |
| Python 离线回归 | 123 项，0 failures / 0 errors |
| JavaScript 回归 | 20 项通过 |
| 空白初始化、合成 demo 初始化、已有数据防覆盖 | 通过 |
| 空白与 demo 首页 | 2 次 HTTP 200 |
| 本轮真实模型调用 | 0 |
| 导出范围与个人资料标记检查 | 未发现匹配；未包含旧 Git 历史与个人资料目录 |

Python 共渲染 85 次，只保留 2 组精确 HTML + ResumeSpec；初始化冒烟另验证 2 次首页响应，不另保留页面。全部检查结果保留，不以留存页数代表覆盖率。

- [Python 完整结果](artifacts/public-source-20260928/test-results.txt)、[汇总](artifacts/public-source-20260928/summary.json)
- [JavaScript 完整结果](artifacts/public-source-20260928/js-results.txt)
- [初始化检查](artifacts/public-source-20260928/init-smoke.json)、[导出检查范围](artifacts/public-source-20260928/export-review.json)
- [可编辑 HTML](artifacts/public-source-20260928/render-editable/resume.html) / [ResumeSpec](artifacts/public-source-20260928/render-editable/resume-spec.json)
- [正式 HTML](artifacts/public-source-20260928/render-static/resume.html) / [ResumeSpec](artifacts/public-source-20260928/render-static/resume-spec.json)

首次导出验证暴露一个测试辅助模块漏包及两项沙箱端口限制；补齐模块并允许本机临时端口后，上述完整回归通过。未执行新的真实模型 API、浏览器人工验收、原生应用人工体验或另一台 Mac 首次安装。个人资料标记与常见凭据模式检查不是完整安全审计。
