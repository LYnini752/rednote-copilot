# Validation scope / 验收范围

This software alpha is intended for one trusted local user. 本项目为本地软件 alpha。

- Automated coverage: strict CSV parsing and weighted ratios, draft export/restore, safe text preview, provider configuration and loopback HTTP, Gradio queue workflows and independent client histories.
- 自动验证：严格 CSV 解析与加权指标、导出/恢复、安全文本预览、模型协议与 Gradio 队列流程、独立会话历史。
- Offline demo and loopback stubs are synthetic; they do not validate real model quality. 离线演示和本地 stub 均为合成数据。
- Browser checks during development covered draft/edit/export/restore/CSV, keyboard traversal and a 492px viewport. New release changes are additionally checked with automated regression tests. 开发阶段已走查基础浏览器流程、键盘和窄屏布局。
- Real provider credentials, billing, live output quality, actual user analytics data and automatic publishing remain unverified or unsupported. 真实模型及用户运营数据未验证，不含自动发帖。
- Source validation excludes credentials, exports, internal handoffs and work logs. Test commands and dependency pins are in the READMEs. 发布源不包含密钥、用户导出或内部协作日志。

See repository Actions for the current Python 3.11–3.13 CI result. CI is not evidence of model accuracy or production multi-user security.
