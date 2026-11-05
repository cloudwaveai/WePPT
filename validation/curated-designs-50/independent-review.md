# CD50 独立验收记录

日期：2026-11-05。角色：独立 Validator（与实现者分开的执行上下文）。基线：`766bd4eb8150292612a04e2390e39f497548ae46`。只读取实现和测试，未修改运行代码或测试。

## 结论

本轮精选案例数据、真实 Studio 上下文传递、策略持久化、非法编号拒绝、自由生成默认路由、显式固定套系/历史绑定兼容的定向验收通过。代码审查未发现这次接入引入的阻断缺陷。

**不能宣称全量测试全绿，也不能据此宣称真实模型的审美生成已验收。** 全量在 Windows 存在既有 POSIX/符号链接/路径兼容问题；缺少 npm 依赖导致的导出问题已补装依赖后逐项复测通过。浏览器由主代理另行验证，本报告不冒充独立浏览器验收。

## 实际检查

- 与用户已认可的 `PPT模板精选50套-清单.json` 逐条比对：50条的名称、分类、用途、观察、短板、适配建议、原始库ID、来源URL和400条预览元数据完全一致。
- 50个新案例ID唯一，30套排版主库、20套视觉增强。案例查询返回副本，调用方修改不会污染缓存。
- 新项目真实 `Studio.context()` 返回50套参考，同时取消未显式选择的默认固定套系契约。
- `create_deck` → `next_job` 确认 `curatedReferenceId` 保存并进入逐页上下文，用户 composition 不变；逐页只携带已选参考，不重复发送完整50套目录。
- 显式选择固定套系仍走本地编排；历史有固定ID但没有偏好记录的任务仍保留固定套系契约。
- 上传对标风格和用户配色的既有定向测试通过。
- 预览页面通过现有认证边界返回；未认证401。HTML有50个案例、400张代表图，主界面有入口。UI实测另见主代理记录。
- 策划参考上下文约13,185字符；选定单案例的页参考上下文约732字符。模型获得文字观察和规则，不会自动获得400张图的视觉输入。

## 测试证据

环境：Windows，Python 3.14，`PYTHONUTF8=1`、`PYTHONPATH=tests`。

1. 定向：`python -m unittest test_curated_designs test_deck_design test_template_packs test_agent_bridge test_style_templates`，**83项，OK，16项既有平台/可选条件跳过**，24.657秒。见 `targeted-final.log`。
2. 全量：`python -m unittest discover -s tests`，**583项，8 failures、24 errors、28 skipped**，410.847秒。见 `python-full.log`。failure/error包括子用例事件，不能简单相减得出通过用例数。
3. 全量中的5个导出失败项，在实现者安装锁定npm依赖后逐项重跑，**5项通过**，6.866秒。见 `export-rerun.log`。
4. 全量中的 `test_palette_endpoints` 连接被Windows中止，单独复测 **1项通过**，2.318秒。见 `palette-rerun.log`。

### 全量异常分类

| 分类 | 原全量事件 | 证据及处理 |
|---|---:|---|
| Codex生图/图片暂存依赖POSIX行为 | 15 errors + 6 failures | Windows没有 `os.O_DIRECTORY/O_NOFOLLOW`；无扩展名shebang假执行器不能按POSIX启动；符号链接创建缺少权限。相关运行模块/测试与HEAD一致，本轮未改。未绕过安全校验来改判通过。 |
| core符号链接测试 | 1 error | WinError 1314，Windows缺少符号链接权限。未改测试。 |
| PPTX导出依赖缺失 | 4 errors + 1 failure | `PPTX_DEPENDENCY_MISSING`。安装项目锁定依赖后5项全部通过。 |
| 公网访问测试的POSIX文件权限/符号链接 | 3 errors | Windows chmod不满足现有0600判断，或WinError 1314。认证检查分支未因本轮新增静态路由而变化。 |
| 路径分隔符断言 | 1 failure | `adaptations\\feedback-flow.md` 与测试期待的 `/` 不同；相关实现和测试未改。 |
| palette HTTP瞬时连接 | 1 error | WinError 10053；独立复测通过。 |

## 首次验证返工

首次直接在Windows执行时，既有代码无encoding参数的 `read_text()` 按GBK解码UTF-8失败；设置 `PYTHONUTF8=1` 后消除。Git初始自动转CRLF使 `spatial_templates.py` 原字节hash与已提交模板不匹配；实现者从HEAD恢复该文件LF原字节，所有固定套系指纹核验匹配，不改校验逻辑。

新增测试最初误用 `next_job()['payload']`。Validator指出实际API是 `next_job()['job']['payload']`，实现者修正后定向全通过。保留 `targeted-before-environment-fix.log` 作为失败过程证据；最终依据是修正后的日志。

## 仍未验证

- 真实模型在同输入下的前后PPT审美质量、生成材质效果和桌面PowerPoint最终显示。
- Linux生产环境全量回归、仓库合并和线上发布。
- 原始PPT全部页面、精确几何/透明度/阴影参数与可编辑素材还原。

本轮交付应表述为“精选案例库及生成上下文接入”，不应表述为“50套PPT已完整原生复刻”或“线上已经更新”。
