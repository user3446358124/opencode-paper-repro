---
description: 查看待处理、已阻断、已批准和已发布的 GitHub 开源发布任务
agent: open-source-publisher
---
调用 `repro_publish(action="list")`，用中文按状态汇总发布任务。对每项显示 publication_id、系统版本、关联 improvement_id、目标仓库、可见性、扫描状态、发布结果或 PR URL。不得显示 Token、用户配置文件内容或项目运行信息。
