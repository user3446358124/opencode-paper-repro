# 模型能力路由与多模态补充

## 原则

系统使用 `native-first` 策略，不绑定任何底座或视觉模型名称。

1. 当前 OpenCode 底座能直接读取图片时，优先使用其原生视觉能力。
2. 当前底座是纯文本模型、图片读取失败或任务需要专门 OCR 时，才调用备用多模态 profile。
3. profile 保存协议、Base URL、模型 ID、能力标签和 API Key 环境变量名；真实密钥保存在统一受保护配置的 `secrets` 区域。
4. 全局配置位于 `~/.config/paper-repro/config.json` 的 `model_routing` 区域，项目仍可在 `.paper-repro/model-routing.json` 覆盖。

## 配置示例

以下命令中的值只是示例，系统不会预置或硬编码：

```bash
paper-repro secrets set MY_VISION_API_KEY

paper-repro models profile set \
  --name vision-fast \
  --protocol openai-compatible \
  --base-url 'https://YOUR-ENDPOINT/v1' \
  --model 'YOUR-VISION-MODEL-ID' \
  --api-key-env MY_VISION_API_KEY \
  --capabilities vision,document,ocr,table,chart,formula

paper-repro models route --task vision --profile vision-fast
paper-repro models route --task document --profile vision-fast
paper-repro models route --task table --profile vision-fast
paper-repro models route --task chart --profile vision-fast
```

查看有效配置：

```bash
paper-repro models show
```

测试：

```bash
paper-repro vision test --input /path/to/page.png --task document
```

PDF 页面：

```bash
paper-repro vision analyze \
  --input paper.pdf \
  --pages '3,7-9' \
  --task table \
  --prompt '逐表格提取行列、数值和脚注，保留不确定项。'
```

## 能力声明

默认 `native.capability=auto`，视觉代理会先尝试当前底座原生读取。已知底座为纯文本时可显式声明：

```bash
paper-repro models native --capability text-only
```

未来切换到原生多模态底座时：

```bash
paper-repro models native --capability vision
```

即使备用 profile 仍存在，原生能力也会优先。


密钥管理和一键清理见 [`UNIFIED_CONFIG_CN.md`](UNIFIED_CONFIG_CN.md)。
