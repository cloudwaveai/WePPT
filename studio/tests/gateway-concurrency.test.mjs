import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {runAI, runStructuredAI} from '../ai.mjs';
import {runImageTool} from '../image-design-ai.mjs';

test('mixed image, editor and structured requests share four live processes, including during cancellation', {
  skip: process.platform === 'win32', timeout: 20000,
}, async () => {
  const dir = await mkdtemp(join(tmpdir(), 'gateway-slots-'));
  const exe = join(dir, 'fake-codex');
  const log = join(dir, 'starts');
  const env = {WEPPT_CODEX_PATH: exe, WEPPT_IMAGE_CODEX_PATH: exe, WEPPT_IMAGE_CODEX_HOME: dir};
  const saved = Object.fromEntries(Object.keys(env).map(key => [key, process.env[key]]));
  const controllers = [], tasks = [];
  const records = async () => (await readFile(log, 'utf8')).trim().split('\n').filter(Boolean).map(JSON.parse);
  async function waitFor(count) {
    for (let i = 0; i < 250; i++) {
      const rows = await records();
      if (rows.length >= count) return rows;
      await delay(20);
    }
    assert.fail('Timed out waiting for ' + count + ' subprocesses');
  }
  function launch(call) {
    const ctl = new AbortController();
    controllers.push(ctl);
    const task = call(ctl.signal);
    tasks.push(task);
    task.catch(() => {});
    return {ctl, task};
  }
  const draw = (signal, name) => runImageTool({signal, directory: dir, prompt: name, background: true});
  try {
    Object.assign(process.env, env);
    await writeFile(log, '');
    await writeFile(exe, `#!/usr/bin/env node
const fs = require('node:fs');
process.on('SIGTERM', () => {});
let input = '';
process.stdin.on('data', data => input += data);
process.stdin.on('end', () => {
  const name = /test-job-[a-z]+/.exec(input)?.[0];
  fs.appendFileSync(${JSON.stringify(log)}, JSON.stringify({pid:process.pid, name})+'\\n');
  setInterval(() => {}, 1000);
});`, {mode: 0o755});
    const drawings = ['a', 'b', 'c', 'd'].map(id => launch(signal => draw(signal, 'test-job-' + id)));
    const first = await waitFor(4);
    const editorReady = Promise.withResolvers(), structuredReady = Promise.withResolvers();
    const structured = launch(signal => runStructuredAI({prompt:'test-job-review', schema:{type:'object'}}, {
      signal, background:true, dataDir:dir, onProgress: () => structuredReady.resolve(),
    }));
    const editor = launch(signal => runAI({action:'draft', message:'test-job-editor', project:{pages:[]}}, {
      signal, dataDir:dir, onProgress: () => editorReady.resolve(),
    }));
    const cancelled = launch(signal => draw(signal, 'test-job-cancelled'));
    await Promise.all([editorReady.promise, structuredReady.promise]);
    cancelled.ctl.abort();
    await assert.rejects(cancelled.task);
    assert.equal((await records()).length, 4);

    const firstPid = first.find(row => row.name === 'test-job-a').pid;
    drawings[0].ctl.abort();
    // The fake child ignores SIGTERM. Its slot must stay occupied until SIGKILL.
    await delay(150);
    assert.doesNotThrow(() => process.kill(firstPid, 0));
    assert.equal((await records()).length, 4);
    await assert.rejects(drawings[0].task);
    assert.throws(() => process.kill(firstPid, 0), {code:'ESRCH'});
    assert.equal((await waitFor(5))[4].name, 'test-job-editor');
    editor.ctl.abort();
    await assert.rejects(editor.task);
    const rows = await waitFor(6);
    assert.equal(rows[5].name, 'test-job-review');
    assert.throws(() => process.kill(rows[4].pid, 0), {code:'ESRCH'});
    structured.ctl.abort();
    await assert.rejects(structured.task);
  } finally {
    for (const ctl of controllers) ctl.abort();
    await Promise.allSettled(tasks);
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, {recursive:true, force:true});
  }
});
