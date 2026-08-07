# PDF 文本层与视觉层联合审计

## 为什么不是二选一

对于可复制文字的 born-digital PDF，`pdftotext`、PyMuPDF 或 pypdf 通常更适合提取精确文字、数字、引用和全文搜索；视觉模型更适合理解页面版面、合并单元格、表格行列关系、脚注、加粗/下划线、架构图、曲线和扫描内容。

因此默认 `targeted` 策略为：

1. 全文先做文本层提取；
2. 自动检查每页文本量、图片、Table/Figure caption；
3. 对扫描页、所有实验表格页、核心方法/架构图页调用视觉能力；
4. 关键数字以文本层为主，视觉用于行列归属和交叉核验；
5. `paper_manifest.json` 明确记录真实调用来源，未调用视觉时不得写成已视觉审计。

## 查看和设置策略

```bash
paper-repro paper policy show
```

默认：

```json
{
  "vision_policy": "targeted",
  "vision_verify_tables": true,
  "vision_verify_method_figures": true,
  "max_vision_pages": 24,
  "dpi": 200
}
```

切换策略：

```bash
paper-repro paper policy set --vision-policy targeted
paper-repro paper policy set --vision-policy on-demand
paper-repro paper policy set --vision-policy all-pages
paper-repro paper policy set --vision-policy off
```

检查某份 PDF：

```bash
paper-repro paper inspect --input /absolute/path/paper.pdf
```

输出：

```text
.paper-repro/current/analysis/pdf_inventory.json
```

其中包含 `recommended_vision_pages` 和每一页推荐调用视觉的原因。

## 四种策略

- `targeted`：推荐默认值。目标表格和核心方法图强制视觉复核。
- `on-demand`：只有文本层不可用或存在歧义时调用视觉，成本最低。
- `all-pages`：每页视觉分析，成本高，适合扫描论文或高价值审计。
- `off`：完全关闭视觉；结果必须记录未做视觉核验。

## 如何确认视觉模型真的被调用

检查：

```text
.paper-repro/current/analysis/vision/
.paper-repro/current/meta/events.jsonl
.paper-repro/current/analysis/paper_manifest.json
```

`paper_manifest.json` 应包含：

```json
{
  "extraction_provenance": {
    "text_extractors": ["pdftotext"],
    "vision_policy": "targeted",
    "vision_calls": 3,
    "vision_pages": [4, 7, 8],
    "failed_vision_pages": []
  }
}
```

若 `vision_calls` 为 0，应明确说明原因，而不是笼统写“备用视觉已配置”。
