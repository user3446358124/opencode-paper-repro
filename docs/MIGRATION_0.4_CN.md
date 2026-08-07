# v0.4.0 升级说明

在原控制 Conda 中解压新版并运行：

```bash
conda activate <control-env>
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
```

完全退出并重启 OpenCode。v0.4.0 不再设置默认底座模型，请在启动参数或 OpenCode 自身配置中选择：

```bash
paper-opencode --auto -m <provider>/<base-model>
```

若底座为纯文本模型，配置备用视觉 profile；若底座已支持视觉，则无需配置，或保留 profile 作为故障后备。详见 `MODEL_ROUTING_CN.md`。
