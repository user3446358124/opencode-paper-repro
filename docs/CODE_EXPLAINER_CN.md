# 代码讲解与调用链文档

## 快速使用

在目标项目目录启动 OpenCode，并确保已有 run 或至少位于 Git 项目中：

```text
/repro-explain all
```

常用范围：

```text
/repro-explain overview
/repro-explain call-chain
/repro-explain paper-core
/repro-explain data-flow
/repro-explain runtime
/repro-explain module models.encoder
/repro-explain file train.py
```

也可以先在终端生成静态索引：

```bash
paper-repro code index
paper-repro code show
```

## 输出

完整模式写入：

```text
.paper-repro/current/report/code-guide/
├── README.md
├── STATIC_STRUCTURE.md
├── CODEBASE_OVERVIEW.md
├── CALL_CHAINS.md
├── PAPER_CORE_IMPLEMENTATION.md
├── DATA_AND_TENSOR_FLOW.md
├── CONFIG_AND_EXPERIMENTS.md
├── RUNTIME_TRACE.md
├── MODULE_INDEX.md
├── READING_ORDER.md
└── OPEN_QUESTIONS.md
```

静态索引写入：

```text
.paper-repro/current/analysis/code_index.json
```

## 讲解内容

- 仓库目录职责、入口文件和建议阅读顺序；
- 数据准备、训练、评测和推理调用链；
- 论文方法、公式、损失和核心模块对应的类、函数与配置；
- 关键 tensor shape、device、dtype、梯度和 loss/metric 聚合；
- 配置继承、CLI 参数、seed、checkpoint 与表格复现实验；
- 静态调用链和实际日志验证后的运行时调用链；
- 动态注册器、decorator、Hydra、callback、hook 和框架隐式调用；
- 缺失实现、近似实现、与论文描述不一致和未确认事项。

## 可信度规则

静态 AST 调用图只是候选关系。动态分派、反射、注册器和配置驱动调用必须结合：

1. README 和配置；
2. `repo_manifest.json`；
3. `reproduction_matrix.json`；
4. 实际执行命令与日志；
5. 必要时的第三方框架官方文档。

每个重要结论应附 `path:line`。无法确认时必须标记“推断”或“尚无运行证据”。
