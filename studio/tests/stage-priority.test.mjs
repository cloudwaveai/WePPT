import test from 'node:test';
import assert from 'node:assert/strict';
import {setImmediate as flush} from 'node:timers/promises';
import {createStageScheduler} from '../stage-pipeline.mjs';

for (const sharedStages of [[], ['drawing']]) {
  test(`queued stages alternate fairly and honour cancellation (shared=${sharedStages.length})`, async () => {
    const scheduler = createStageScheduler({drawing: 1}, {sharedStages, sharedLimit: 1});
    const order = [];
    const controller = new AbortController();
    const gate = Promise.withResolvers();
    const blocker = scheduler.run('drawing', () => gate.promise);
    await flush();
    function enqueue(name, prefer, signal) {
      return scheduler.run('drawing', () => order.push(name), {prefer, signal});
    }
    const cancelled = assert.rejects(enqueue('cancelled', true, controller.signal), {name: 'AbortError'});
    const waiting = [
      enqueue('ordinary A', false), enqueue('ordinary B', false),
      enqueue('cover A', true), enqueue('background reuse', true), enqueue('cover B', true),
    ];
    await flush();
    controller.abort();
    assert.equal(scheduler.snapshot().drawing.active, 1);
    assert.equal(scheduler.snapshot().drawing.waiting, 5);
    gate.resolve();
    await Promise.all([blocker, cancelled, ...waiting]);
    assert.deepEqual(order, ['cover A', 'ordinary A', 'background reuse', 'ordinary B', 'cover B']);
    assert.deepEqual(scheduler.snapshot().drawing, {limit: 1, active: 0, waiting: 0});
  });
}
