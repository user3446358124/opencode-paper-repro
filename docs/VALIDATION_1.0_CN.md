# v1.0.0 验证记录

本版本在打包前完成以下自动化验证：

- Python 控制器编译；
- `bootstrap.sh`、卸载脚本和 smoke test 的 Shell 语法；
- 所有 JSON Schema 与配置示例解析；
- 隔离 smoke test；
- 从系统源码快照生成公开快照；
- `.paper-repro`、PDF、数据、模型、checkpoint 和日志排除；
- 统一配置真实密钥的原值、Base64 和 URL 编码阻断；
- 当前进程中临时 API Key/Token 环境变量阻断；
- 公共仓库缺少许可证时阻断；
- 批准绑定目标仓库、可见性、快照摘要和公开元数据策略；
- 新仓库首次推送模拟；
- 已有仓库无变化检测；
- 已有仓库变更分支和 Pull Request 模拟；
- 覆盖安装后全局 OpenCode Commands、Agent、Tool 与系统源码快照存在性；
- 公开快照中的最小权限 CI 和 Issue 表单存在性。

GitHub 网络、账户权限、组织策略和实际 Token 只能在用户自己的服务器与账户中最终验证。发布功能在实际写入前仍要求人工确认。
