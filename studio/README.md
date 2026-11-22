# WePPT Studio

此目录保存 2026 年 11 月 19 日运行的 Node.js 工作台应用源码。仓库根目录保留早期 Python 工作台。两个版本使用不同的项目存储格式。

## 本地启动

在此目录使用 Node.js 22 或更高版本运行以下命令。

```sh
npm ci --include=dev
npm start
```

在浏览器打开 http://127.0.0.1:8788 。本地项目默认写入 `data/`。AI 生成需要配置当前用户的模型执行环境。Python 文档导入和浏览器渲染依赖见 `Dockerfile.prod`。该文件记录基础依赖；线上登录网关、站点配置和运行数据由部署方单独管理。

代码包含 150 项模板元数据、20 份可编辑版式和带许可证的矢量素材库。设计网站参考图及模板预览使用部署方持有的原件。完整预览需要在 `public/assets/templates/`、`public/assets/theme-previews/` 以及 `vendor/template-source-originals/` 放入对应资源。每项模板的来源和资源路径在 `public/templates.json` 中。

## 排查生成慢

用工作区的 `ai-timings.jsonl` 可以复算各类调用的次数、中位耗时和 P90。脚本在本地读取计时文件，只输出分组统计。

```sh
python3 scripts/summarize-timings.py data/ai-timings.jsonl
```

要判断用户要等多久才能看到第一页，还需要结合对应任务的 `createdAt`、`pipelineTimings.firstDrawingStartedAt` 和 `pipelineTimings.firstPageReadyAt`。多页任务的阶段可能同时运行，不能将每次调用时长相加当作用户等待时间。
