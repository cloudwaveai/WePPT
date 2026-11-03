# 先选模板，再生成适配 · 2026-10-30

已发布 editor-36 到 https://ppt.bbstack.date/ 。默认“推荐模板/找模板”不再进入旧 scene_patch 快捷修改。它读取当前可编辑页的实际文字、图片数量、表达要求与可识别内容数量，以本地规则检索 44 页原稿模板，右侧展示 3 个候选原图、理由和适配条件。独立的原稿模板不按旧通用布局映射合并。文字工具单独收起。

确认模板前模型调用为零。点击“选这个模板”只打开原模板和当前页；再点击“生成适配预览”才进入 editor-34/35 已实测的 LLM 适配；应用仍需显式确认。选版是启发式筛选，不声称模型已理解或审美审核全部模板；用户可补充表达要求或浏览完整模板库。

验证：

- Mac/Linux 各 34 项相关后端检查通过，包含鉴权、跨站、版本、项目范围、预览不写入和适配内容保持；42 项 JS 检查通过。
- 部署后独立项目真实浏览器打开桌面与手机页面，右侧显示模板原图；“问题与方案对照”和“四步流程”返回不同候选。四步流程优先四阶段原稿。
- 选模板与打开预览仅发送两次 /api/templates/match，没有 editor/suggest、templates/adapt 或外部分类调用，当前场景逐字段保持，浏览器 JS 错误为零。
- 亲自查看 right-template-recommendations.png、selected-template-before-generation.png、mobile-template-recommendations.png。原图文件仅调整显示大小。
- 7 个关键部署文件哈希与本地相同。发布前无运行或排队任务，备份 /data/backups/before-editor-36.sqlite。原用户项目与 before-editor-34 的 44 条场景历史保持，8 页、5 轮输入不变。

证据：本目录日志、deployed-files.json、original-project-check.json，以及 ../../outputs/weppt-template-matching-2026-10-30/ 。本次未重复调用生成模型；已有真实生成证据在 ../template-adaptation-2026-10-30/ 。
