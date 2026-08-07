---
description: 查看、启用或关闭论文复现的基础联网与 MCP 能力
agent: repro-orchestrator
---
调用 `repro_mcp` 查看当前状态。向用户说明：网页发现优先使用 OpenCode 内建 websearch，已知 URL 使用 webfetch；Context7 用于公共依赖文档；GitHub 只读用于 Release/Issue/PR；Hugging Face 用于模型和数据集；Brave 仅作为备用搜索源。不得启用 filesystem、shell 或写权限型 GitHub MCP。
