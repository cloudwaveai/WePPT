// Run against an existing local server; credentials are read at runtime, never printed.
// GUIDE_STARTUP_LOG=/path/to/server-output node tests/guide-browser.cjs
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require('/Users/auntlee/.npm/_npx/e41f203b7505f1fb/node_modules/playwright');
(async () => {
  const log = fs.readFileSync(process.env.GUIDE_STARTUP_LOG, 'utf8');
  const authURL = log.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[^\s"\\]+/)[0];
  const origin = new URL(authURL).origin;
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 1000 } });
  const page = await context.newPage(); const errors = [];
  page.on('pageerror', e => errors.push(e.message)); page.on('dialog', d => d.accept());
  try {
    await page.goto(authURL);
    const result = await context.request.post(origin + '/api/projects', { data: { title: '引导页浏览器验证（独立测试项目）' } });
    assert.equal(result.status(), 200); const project = (await result.json()).projectId;
    const path = `${origin}/guide.html?project=${project}`;
    await page.goto(path); await page.locator('#handoff-brief').waitFor({ state: 'visible' });
    await page.waitForFunction(() => !document.querySelector('.guide-sections').inert);
    await page.locator('#topic').fill('试点计划'); await page.locator('#audience').fill('业务负责人'); await page.locator('#action').fill('批准试点');
    await page.locator('#slot-options').fill('A / B'); await page.locator('#followup-missing').fill('待补同口径成本');
    await page.locator('#materials').selectOption('ready'); assert.equal(await page.locator('#followup-missing').count(), 0);
    await page.locator('#materials').selectOption('partial'); assert.equal(await page.locator('#followup-missing').inputValue(), '待补同口径成本');
    await page.locator('.template-card').first().waitFor(); await page.locator('.template-card').first().click();
    await page.locator('[data-task="process"]').click(); assert.equal(await page.locator('#slot-options').count(), 0); assert.equal(await page.locator('#template-warning').isVisible(), true);
    await page.locator('#add-page').click(); assert.match(await page.locator('#guide-status').innerText(), /不匹配/);
    await page.locator('[data-task="compare"]').click(); assert.equal(await page.locator('#slot-options').inputValue(), 'A / B');
    await page.locator('#page-title').fill('方案比较'); await page.locator('#conclusion').fill('建议先做 A'); await page.locator('#add-page').click();
    await page.locator('#new-page').click(); await page.locator('[data-task="process"]').click(); await page.locator('#page-title').fill('落地步骤'); await page.locator('#slot-steps').fill('验证 / 李 / 下周 / 结果'); await page.locator('#add-page').click();
    await page.locator('#deck-outline li').nth(1).getByRole('button', { name: '上移', exact: true }).click();
    assert.match(await page.locator('#deck-outline li').first().innerText(), /落地步骤/);
    await page.locator('#deck-outline li').first().getByRole('button', { name: '移除', exact: true }).click(); await page.locator('#restore-page').click();
    await page.locator('#deck-outline li').nth(1).getByRole('button', { name: '载入编辑', exact: true }).click(); assert.equal(await page.locator('#slot-options').inputValue(), 'A / B');
    await page.locator('#conclusion').fill('建议先做 A，降低试点成本'); await page.locator('#add-page').click(); await page.locator('#build-brief').click();
    const brief = await page.locator('#brief').inputValue(); for (const text of ['封面', '目录', '结束页', '落地步骤', '方案比较', '模板 ID', '不自动发送', '降低试点成本']) assert.ok(brief.includes(text), text);
    await page.locator('#qa-question').fill('应该先说什么？'); await page.locator('#qa-answer').fill('先说听众要作出的决定。'); await page.locator('#qa-rule').fill('先明确决策，再组织依据。'); await page.locator('#qa-source').fill('我的项目复盘，2026-10-27'); await page.locator('#save-qa').click();
    await page.getByRole('button', { name: '加入精选', exact: true }).first().click(); await page.locator('#favorite-records textarea').first().fill('相同视觉风格，内容槽位中性，适合比较方案');
    await page.locator('#curated-only').check(); assert.equal(await page.locator('.template-card').count(), 1);
    await page.waitForFunction(() => /服务器已保存/.test(document.querySelector('#draft-save').textContent) && /服务器已保存/.test(document.querySelector('#experience-save').textContent));
    await page.reload(); await page.waitForFunction(() => !document.querySelector('.guide-sections').inert);
    assert.equal(await page.locator('#deck-outline li').count(), 2); assert.match(await page.locator('#qa-records').innerText(), /先明确决策/); assert.match(await page.locator('#favorite-records textarea').inputValue(), /中性/);
    await page.locator('#personal details').last().locator('summary').click();
    await page.locator('#import-experience').setInputFiles({ name: 'experience.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ schema: 'weppt-guide-experience-v1', projectId: 'other-project', document: { records: [{ id: 'imported-qa', question: '复用问题', answer: '复用回答', rule: '复用规则', source: '原项目手动记录', task: 'compare', templateId: '' }], favorites: [] } })) });
    await page.waitForFunction(() => document.querySelector('#import-preview').textContent.includes('待追加 1 条问答')); assert.match(await page.locator('#import-preview').innerText(), /待追加 1 条问答/); await page.locator('#confirm-import').click(); assert.match(await page.locator('#qa-records').innerText(), /复用规则/);
    await page.locator('#import-experience').setInputFiles({ name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from('{"document":{}}') }); await page.waitForFunction(() => document.querySelector('#import-preview').textContent.includes('无法导入')); assert.match(await page.locator('#import-preview').innerText(), /无法导入/); assert.equal(await page.locator('#confirm-import').isDisabled(), true);
    await page.locator('#style-group').selectOption('deep-blue-tech'); assert.match(await page.locator('#catalog-status').innerText(), /0 个匹配/); await page.locator('#style-group').selectOption('all');
    const other = await context.newPage(); other.on('dialog', d => d.accept()); await other.goto(path); await other.waitForFunction(() => !document.querySelector('.guide-sections').inert);
    await page.locator('#topic').fill('先保存的服务器版本'); await page.waitForFunction(() => /服务器已保存/.test(document.querySelector('#draft-save').textContent));
    await other.locator('#topic').fill('冲突中的本地版本'); await other.locator('#save-conflict').waitFor({ state: 'visible' }); assert.match(await other.locator('#draft-save').innerText(), /冲突/);
    const stored = await context.request.get(`${origin}/api/guide/draft?project=${project}`); assert.equal((await stored.json()).document.fields.topic, '先保存的服务器版本');
    await other.locator('#reload-server').click(); await other.locator('#save-conflict').waitFor({ state: 'hidden' }); assert.equal(await other.locator('#topic').inputValue(), '先保存的服务器版本'); await other.close();
    await page.setViewportSize({ width: 390, height: 844 }); await page.screenshot({ path: '/tmp/weppt-guide-mobile.png', fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false); await page.locator('#outline').scrollIntoViewIfNeeded(); await page.screenshot({ path: '/tmp/weppt-guide-mobile-viewport.png' });
    await page.setViewportSize({ width: 1400, height: 1000 }); await page.locator('#outline').scrollIntoViewIfNeeded(); await page.screenshot({ path: '/tmp/weppt-guide-desktop.png' });
    // Confirm existing explicit handoff contract and lack of automatic chat submission.
    let chatPosts = 0; page.on('request', req => { if (req.url().includes('/api/chat') && req.method() === 'POST') chatPosts++; });
    await page.locator('#handoff-brief').click(); await page.waitForURL(/guideDraft=/); assert.equal(chatPosts, 0);
    // Legacy local draft migrates only after GET has established the server revision.
    const migrationResult = await context.request.post(origin + '/api/projects', { data: { title: '引导页旧草稿迁移验证' } }); const migrationProject = (await migrationResult.json()).projectId;
    const migration = await context.newPage(); migration.on('dialog', d => d.accept());
    await migration.goto(origin); await migration.evaluate(id => localStorage.setItem(`weppt:guide:v1:${id}`, JSON.stringify({ fields: { topic: '旧浏览器草稿' }, branches: {}, task: 'compare', brief: '旧编辑稿' })), migrationProject);
    let firstGet = true;
    await migration.route('**/api/guide/draft?*', async route => { if (route.request().method() === 'GET' && firstGet) { firstGet = false; await new Promise(resolve => setTimeout(resolve, 350)); } await route.continue(); });
    await migration.goto(`${origin}/guide.html?project=${migrationProject}`); assert.equal(await migration.locator('.guide-sections').evaluate(e => e.inert), true);
    await migration.waitForFunction(() => !document.querySelector('.guide-sections').inert); assert.equal(await migration.locator('#topic').inputValue(), '旧浏览器草稿');
    await migration.waitForFunction(() => /服务器已保存/.test(document.querySelector('#draft-save').textContent));
    const migrated = await context.request.get(`${origin}/api/guide/draft?project=${migrationProject}`); assert.equal((await migrated.json()).document.brief, '旧编辑稿');
    await migration.close();
    assert.deepEqual(errors, []);
    console.log('PASS: conditional answers, template mismatch, deck edit/reorder/remove/restore, complete brief, personal Q&A/favorites, persistence, stale conflict/reload, mobile layout, explicit handoff. Project: ' + project);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
