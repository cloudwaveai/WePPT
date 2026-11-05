# CD51 独立验收（最终）

2026-11-05；独立 Validator，只读实现与测试。验收依据：`docs/product/retire-old-template-library.md`。

## 最终结论

本轮退休旧模板公开入口的定向验收通过。首轮发现的CLI/MCP遗漏已修复；旧测试中的偏好/上下文断言已按用户明确的新契约更新，并保留历史文档内容、原图归属、撤销、防重绘、版本hash与Logo发布门禁检查。未发现剩余的本轮阻断缺陷。

**全量不是全绿。** 本轮实际全量结果是589项、9 failures、20 errors、24 skipped；其中3个退休前的上下文断言经修正后，相关两个模块18项复验通过。其余异常与上一轮已记录的Windows/POSIX差异一致，未通过改测试或放宽安全校验掩盖。不能将本结论表述为Linux生产全量已通过或线上已更新。

## 最终证据

- 扩展定向命令：`PYTHONUTF8=1 PYTHONPATH=tests python -m unittest test_retired_templates test_curated_designs test_http test_reference_library test_deck_design test_template_packs test_studio test_user_templates test_style_templates test_cli test_mcp`。
- 结果：**122项，OK，6项MCP可选依赖未安装而跳过**，85.406秒。日志 `targeted-rework.log`。CLI模板列表/有效详情/拒绝旧ID使用真实子进程验证；MCP公开函数与资源映射完成代码审查，不能声称MCP真实stdio集成通过。
- 全量：`python -m unittest discover -s tests`，**589项，9 failures、20 errors、24 skipped**，384.821秒；17:19:20启动的单次进程。日志 `python-full.log`。
- 全量发现的三个过期断言涉及 `test_templates` 两项和 `test_reference_adaptation` 一项。修正后仅重跑这两个模块，**18项全部通过**，13.963秒；日志 `legacy-context-rerun.log`。没有重复全量或修改运行逻辑来迎合旧契约。
- 新增50张JPEG封面全部独立解码通过；`pyproject.toml`包含`web/curated-covers/*.jpg`。
- 原内容、图片、版本与撤销的相关定向模块通过。公开HTTP库恰为50条referenceOnly；CLI公开目录也恰为50条；旧ID详情拒绝。

### 全量异常分类

| 分类 | 全量事件 | 结论 |
|---|---:|---|
| Codex图片生图/暂存的POSIX假可执行器、O_DIRECTORY、符号链接 | 15 errors + 6 failures | 与CD50已记录的Windows限制一致，相关实现未改。 |
| core符号链接夹具 | 1 error | WinError 1314，既有权限限制。 |
| 公网token权限和符号链接 | 3 errors | Windows chmod/符号链接与POSIX约定不同，安全检查未放宽。 |
| 设计指导路径分隔符 | 1 failure | Windows反斜杠与测试期望正斜杠不符，既有问题。 |
| 退休前的AI上下文契约 | 1 error + 2 failures | 三处过期断言已更新；保留currentSceneTemplateId等历史兼容检查，相关18项复验通过。 |

failure/error包含子用例事件，不能简单相减声称某个通过用例数。上轮缺少pptxgenjs的导出失败本轮不再出现；上轮palette连接偶发错误本轮也未出现。

## 验收范围与边界

公开HTTP/CLI/MCP模板目录切换为精选50套，旧固定套系选择和应用HTTP入口停用。底层历史解析/编排数据仍存在，以读取已有稿件和处理已保存绑定任务；这不应被描述为磁盘上的所有旧资产已物理删除。新稿不再从退休偏好自动绑定，AI上下文无旧候选列表。

本报告未进行浏览器操作；主代理另行保存入口、卡片、手机布局等实测证据。未运行真实模型审美对照，不代表用户审美验收。未验证Linux部署、合并或线上发布。

## 首轮记录（历史，已完成返工）

HTTP精选目录、旧入口停用、新稿上下文清理等新测试通过；定向整体尚未通过。发现CLI/MCP仍公开完整旧目录，不能把这轮表述为所有面向用户/Agent的旧库入口均已移除。

命令：`PYTHONUTF8=1 PYTHONPATH=tests python -m unittest test_retired_templates test_curated_designs test_http test_reference_library test_deck_design test_template_packs test_studio test_user_templates test_style_templates`。

结果：109项，3 failures、2 errors，76.909秒。日志：`targeted.log`。按要求，定向未通过前不启动全量。

## 具体问题

1. **公开CLI/MCP仍暴露旧库（实质遗漏）**：`Workbench.list_templates()` 实测147条，覆盖旧 `_REFERENCE` 全部75条。`cli.py` 的模板列表、`mcp_server.py` 的 `ppt_template_get` 和 `ppt://templates` 直接使用该接口。这些是公开的Agent入口，不是历史文档内部渲染。建议在公开适配层返回50条curated参考并拒绝旧详情访问，同时保留底层历史解析能力。
2. **HTTP旧guide测试契约过期**：`test_content_guide_assets_are_authenticated_and_read_only` 期待200，当前303；需按明确退休/跳转决定更新，但继续验证认证边界。
3. **4个固定套系测试夹具需要转为历史绑定任务**：旧测试通过 `packs.select` 偏好再创建新稿，已被CD51明确取消，故无template_id。涉及 `test_select_revision_and_whole_deck_preference`、`test_template_pages_compile_locally_without_runner`、`test_attachment_must_belong_to_project`、`test_template_change_and_external_redraw_rejected`。不应恢复已退休的新稿偏好绑定；应区分“偏好不再影响新稿”的新断言与“已有绑定稿件继续编排/保留原图归属及禁止外部重绘”的兼容夹具，后者使用已保存的显式绑定。

## 首轮通过的范围

- HTTP `/api/templates` 恰为50条referenceOnly；旧75条不在返回值。
- 旧模板预览/匹配/应用等禁用路径保留认证，返回410，已有文档场景未变化。
- 新项目即使保存旧偏好，AI上下文也不再包含旧模板列表和推荐，固定套系契约为空。
- 精选封面ID验证和访问认证保留。
- 用户上传库、用户模板与对标风格相关定向测试通过。

浏览器操作由主代理另行验收；本报告未进行视觉验收，不据此声称上线。
