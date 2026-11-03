# 语义关系与原生箭头优化

2026-10-30。用户授权继续直接优化。20:35 CST 开发环境从 editor-40 更新为 editor-42；editor-41 仅为隔离候选。

## 修改与原因

1. 旧路由把所有反馈回路交给上游 Loop 参考；该参考强制共享中心及外围循环，容易把“筛选与保存”这个操作变成存储实体。现在普通反馈路径使用项目适配 `adaptations/feedback-flow.md`，只有内容明确出现共享状态才建议 hub-loop。上游文件与许可证保持原样。
2. 模板生成与复核接收独立的原始语义依据，包含完整原文和备注；新页复核使用保存的内容方案。区分原始事实与候选几何，不把候选错误连线当事实。源内容明确时直接修正；真实歧义仍提示用户。
3. 复核收到上一轮的完整发现，逐项核对修正。仍最多一次修正、一次复核，不增加模型调用轮数。
4. line 新增可选布尔 startArrow/endArrow。网页箭头与线条作为同一对象移动，PPTX 导出为原生可编辑线端点，不使用图片。旧场景不注入新字段，旧符号箭头保持兼容。模型上下文、校验、局部编辑与导出同步支持。

## 真实模型复验

- editor-41：从上一版错误候选继续，73.63 秒、两次 DeepSeek Flash 看图调用。模型将错误中心图改为“输入→保存→检索→执行；执行→纠错→保存”，原文保留、无溢出。复核仍发现符号箭头偏离线条，状态 needs_attention。其复核返回的额外修改未执行，未突破一次修正上限。此轮合成脚本只给标题和备注，尚未识别“反馈返回”措辞而选 process，后续补齐该路由识别并测试。
- editor-42：从 editor-41 保存候选继续，39.17 秒、两次看图调用。真实使用 cycle 指导，删除漂浮符号并加入原生线端点；复核 PASS，status=revised_and_reviewed，humanAccepted=false。最终 23 个对象、11 段原文完整、无溢出，原用户场景不变。
- 两轮分别验证了关系重排与新箭头能力。不是从空白一次生成的 one-shot 证明，也没有假称用户验收。原图、报告和失败记录全部保留。

## 检查

- 第一阶段 Mac/Linux 各 40 项相关测试通过。加入原生箭头后 Mac 63 项通过；最终 Linux 镜像同组 63 项通过，含四方向、字段类型、旧场景兼容、局部编辑、PPTX 端点与内容保护。测试集合重叠，不相加。
- 四方向场景实际渲染网页及 PPTX→PDF→PNG，方向一致。样例 PPTX 读回 11 段原文逐项相等，没有图片替代文字或箭头；Office 文件校验通过。
- 浏览器最终样例及导出实际打开查看。首次 LibreOffice 渲染因本机字体配置缺 CJK 显示方框，原件保留为 font-missing-first-render.pdf；为验证进程设置已有 Noto Sans CJK SC 替代 Microsoft YaHei 后正确渲染。未修改用户系统字体设置或 PPTX 原字体，未把字体替代渲染称作 PowerPoint 实机测试。
- 初次 Office 校验的默认 Python 缺 defusedxml；使用已有 Miniconda Python 后通过，未额外安装依赖。初次 PDF 预览的默认 Python 缺 fitz，使用已有 pdftoppm 完成检查。
- 10 个实际部署文件与本地 SHA256 一致。发布前无活动文字/图片任务；原 8 页、5 轮及 47 条场景历史与 before-editor-42 备份一致。

## 公网验证边界

首次浏览器报 ERR_CERT_COMMON_NAME_INVALID。本机系统 DNS 返回 223.26.52.12、134.122.183.239、134.122.183.178；1.1.1.1 与 8.8.8.8 均返回已登记源站 43.153.76.85。源站 SNI 证书为 ppt.bbstack.date，Let's Encrypt 签发，有效期 2026-10-24 至 2027-01-22。

浏览器复验临时将该域名解析到已知源站，保留 TLS 域名和完整证书校验，不使用 ignoreHTTPSErrors。最初仅 Chromium 采用映射，独立 APIRequestContext 仍受系统 DNS 影响；最终同源读取也通过浏览器 fetch。原始失败日志与最终回执分别保留，没有修改系统 DNS、Caddy 或证书。

最终桌面/手机浏览器检查通过：默认 creative、两种内容返回不同模板、选择和预览不调用模型、原场景保持、无横向溢出或 JS 错误。回执 `deployed-browser-origin-recheck.log`。这是固定正确源站后的通过，不宣称本机默认 DNS 已恢复。

## 产物与回退

最终样例：`outputs/weppt-semantic-flow-2026-10-30/evidence42/final/candidate.png`；可编辑单页：`Agent-Memory-optimized.pptx`；正确字体替代渲染在 `cjk-render/`。原 PNG 逐字节复制到 `/Users/auntlee/Pictures/Codex生成图片/WePPT/20261030-semantic-flow-evidence42/agent-memory-optimized.png`，未压缩、未覆盖原有图片。

备份 `/data/backups/before-editor-42.sqlite`；保留 editor-40 镜像。新增 line 属性需要新版读取器：回退旧代码前须确认发布后数据是否已使用这些属性，不能直接回退导致新场景无法读取，更不能用旧数据库覆盖新写入。优先向前修复。
