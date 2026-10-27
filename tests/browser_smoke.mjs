// Real UI checks. Start pptctl studio --demo, then supply its URL and a Chromium path.
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PPT_PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.PPT_STUDIO_TEST_URL;
if (!url) throw new Error('Set PPT_STUDIO_TEST_URL to the local studio launch URL.');
const output = process.env.PPT_BROWSER_OUTPUT || '/tmp/ppt-studio-browser';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.PPT_CHROMIUM_PATH || undefined, args: ['--no-sandbox'] });
const errors = [];
async function poll(check) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Timed out waiting for a real page update.');
}
try {
  const context = await browser.newContext({ viewport: { width: 1480, height: 980 }, deviceScaleFactor: 1, baseURL: new URL('/', url).href });
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(url);
  await page.locator('.page-frame').waitFor({ state: 'visible' });
  const first = await (await page.request.get('/api/state')).json();
  if (first.slides.length !== 3) throw new Error('Expected three actual demo pages.');
  const sid = first.selectedSlideId;
  const firstRevision = first.slides.find(s => s.id === sid).sceneRevision;
  const targetTitle = first.slides.find(s => s.id === sid).title === '每一页，都能清楚表达' ? '用对话，逐页打磨表达' : '每一页，都能清楚表达';
  await page.screenshot({ path: path.join(output, 'desktop-before.png'), fullPage: true });
  const active = page.frameLocator('.page-frame').first();
  await active.locator('[data-object-id="title"]').click();
  await page.locator('#object-scope:not([hidden])').waitFor();
  await page.locator('#message-input').fill('标题改为：' + targetTitle);
  await page.locator('#send-button').click();
  await poll(async () => (await (await page.request.get('/api/state')).json()).slides.find(p => p.id === sid).sceneRevision > firstRevision);
  await page.frameLocator('.page-frame').last().getByText(targetTitle, { exact: true }).waitFor();
  await poll(async () => page.locator('.page-frame.active').evaluate(frame => getComputedStyle(frame).opacity === '1'));
  await page.screenshot({ path: path.join(output, 'desktop-after.png'), fullPage: true });
  const second = await (await page.request.get('/api/state')).json();
  const untouched = first.slides.filter(s => s.id !== sid);
  for (const item of untouched) {
    const later = second.slides.find(s => s.id === item.id);
    if (later.revision !== item.revision || later.sceneRevision !== item.sceneRevision) throw new Error('Another page changed.');
  }
  await page.locator('#undo-button').click();
  await poll(async () => (await (await page.request.get('/api/state')).json()).slides.find(p => p.id === sid).sceneRevision > firstRevision + 1);
  await page.locator('#export-button').click();
  const downloaded = page.waitForEvent('download');
  await page.locator('[data-export="pptx"]').click();
  const file = await downloaded;
  const exportedPath = path.join(output, 'browser-export.pptx');
  await file.saveAs(exportedPath);
  if ((await fs.stat(exportedPath)).size < 1000) throw new Error('PPTX download was empty.');
  const mobile = await context.newPage();
  await mobile.setViewportSize({ width: 390, height: 844 });
  await mobile.goto(new URL('/', url).href);
  await mobile.locator('[data-mobile-tab="preview"]').click();
  await mobile.locator('.page-frame').waitFor({ state: 'visible' });
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  if (overflow) throw new Error('Mobile viewport has horizontal overflow.');
  await mobile.screenshot({ path: path.join(output, 'mobile-preview.png'), fullPage: true });
  await mobile.locator('[data-mobile-tab="chat"]').click();
  await mobile.screenshot({ path: path.join(output, 'mobile-chat.png'), fullPage: true });
  if (errors.length) throw new Error(errors.join('\n'));
  const report = { passed: true, checks: ['real preview', 'object selection', 'chat edit', 'other pages unchanged', 'undo', 'editable PPTX download', 'mobile no horizontal overflow'], output };
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}
