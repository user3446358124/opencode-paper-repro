# v0.7.0 覆盖升级与统一配置迁移

## 覆盖安装

```bash
conda activate <paper-repro控制环境>
unzip opencode-paper-repro-starter-v0.7.0.zip
cd opencode-paper-repro-starter
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r
```

完全退出并重新启动 `paper-opencode`。

## 旧配置自动迁移

首次运行时，系统会从以下旧文件导入已有内容：

```text
~/.config/paper-repro/model-routing.json
~/.config/paper-repro/mcp-settings.json
~/.config/paper-repro/secrets.json
```

新来源文件为：

```text
~/.config/paper-repro/config.json
```

旧文件不会立即删除，确认新配置正常后可执行：

```bash
paper-repro config reset --scope global --yes
```

注意：该命令也会删除新配置。若只想删除旧文件，请先备份新 `config.json`，再手工删除三个旧文件。

## 将现有环境变量持久化

```bash
paper-repro secrets import-env --known
paper-repro secrets list
```

对自定义底座变量：

```bash
paper-repro secrets import-env MY_BASE_API_KEY MY_VISION_API_KEY
```

## 验证

```bash
paper-repro config show
paper-repro secrets list
paper-repro models show
paper-repro mcp status
paper-repro doctor
```

`config.json` 权限应为 `600`。
