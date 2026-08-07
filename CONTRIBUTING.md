# Contributing

感谢帮助改进 paper-repro。请只提交能够改善通用系统能力的改动。

## 隐私边界

提交 Issue、Pull Request 或测试材料前，请确认不包含：

- API Key、Token、密码、私钥、认证文件；
- 论文项目源码、私有仓库内容、PDF、数据集、模型或 checkpoint；
- 训练日志、运行结果、服务器主机名、用户名、Home 路径或项目绝对路径。

请使用最小可复现示例、占位路径和合成数据。

## 修改流程

1. 从干净分支修改；
2. 运行 `python -m py_compile scripts/reproctl.py`；
3. 运行 `bash -n bootstrap.sh scripts/uninstall.sh tests/smoke_test.sh`；
4. 运行 `PAPER_REPRO_SELF_TEST=1 bash tests/smoke_test.sh`；
5. 在 Pull Request 中说明风险、测试范围和是否影响安全边界。

涉及权限、凭据、外部写入、Conda 执行或隐私扫描的修改，应视为高风险并要求人工审查。
