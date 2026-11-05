# CD50 · 精选案例接入验收

2026-11-05。基线 `766bd4eb8150292612a04e2390e39f497548ae46`。

## 实现

用户已确认的50套加入运行数据和设计栏预览目录，保留400张代表图、来源、优点、短板与适配建议。策划可保存`strategy.curatedReferenceId`，逐页任务继承同一案例。未选择固定套系的新项目使用自由排版上下文；明确选定与历史绑定套系保留原编译路径。

## 已执行

- `python -m compileall -q ppt_workbench`：通过。
- 独立Validator：`PYTHONUTF8=1 PYTHONPATH=tests python -m unittest test_curated_designs test_deck_design test_template_packs test_agent_bridge test_style_templates`：83项，16项原有条件跳过，其余通过。
- `node tests/ui_logic.mjs`：47项通过。
- 真实浏览器：从编辑器点击“设计”→“精选设计案例”，50卡片、400代表图（加50张重复封面共450个img）全部解码；搜索、用途筛选30条、展开、放大/Escape关闭通过；390px无横向溢出，无页面JS错误。
- 图片检查：每套ID、来源及8张代表图记录与用户确认的清单一致。
- 全量执行583项，初轮8失败、24错误、28跳过；补齐锁定npm依赖后5项PPTX导出补测通过，1项连接中止补测通过；其余定位为Windows的POSIX/符号链接/路径兼容条件。未重跑或宣称全量全绿。

证据：`browser-check.json`、`editor-entry.png`、`catalog-desktop.png`、`catalog-mobile.png`。独立审查和全量回归结论见同目录`independent-review.md`。

## 环境与限制

Windows Python默认GBK曾导致旧catalog读取失败；设置`PYTHONUTF8=1`后复验。Git自动CRLF曾改变既有spatial_templates.py源码指纹；恢复HEAD原始LF字节，不改渲染器逻辑与基准哈希。保留失败说明，不把首次失败算通过。

浏览器初轮旧样式读取失败也来自GBK环境；修正环境重启同一服务后重新从真实入口检查。界面机械检测对原有编辑器样式给出多项既存告警，本轮只增加一条沿用ribbon-more的链接，没有扩大为全界面重设计。

本轮没有真实模型整稿或同模型前后审美基准。截图证明案例入口和预览可用，不证明AI生成质量；这50套没有变成可执行母版，也未自动把400图传给视觉模型。旧视觉返工卡继续保持原状态，不自评审美accepted。

GitHub上游当前账户只有READ权限；将以开发副本的合并请求交付。未合并、未部署，线上行为不能据此宣称已更新。
