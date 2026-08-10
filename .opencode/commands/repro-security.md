---
description: 查看 paper-repro 项目执行沙箱、任务密钥与下载写入边界
---

执行 `paper-repro security show`，用中文解释：

1. 当前项目沙箱模式与 `bwrap` 是否可用；
2. 第三方项目任务默认不会继承控制平面的 API Key/Token；
3. 当前项目显式允许向任务注入的密钥变量名；
4. 下载器允许写入的目录边界；
5. 如果沙箱不可用，不要替用户关闭沙箱。只有用户明确说明该仓库已经审查且愿意接受风险时，才提示其手工执行：
   `paper-repro security sandbox set --mode trusted-off --yes`。

不要展示任何密钥值。
