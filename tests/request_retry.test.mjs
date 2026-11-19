import test from 'node:test';
import assert from 'node:assert/strict';
import { apply, waitForRetry } from '../vendor/plugins/request-retry/index.mjs';

function fixture(wait = async () => true) {
  let handler, cleanup;
  const events = [], waits = [];
  const ctx = {
    on(_event, callback) { handler = callback; return () => {}; },
    effect(callback) { cleanup = callback(); },
  };
  apply(ctx, {}, { wait: (ms, signal) => { waits.push(ms); return wait(ms, signal); } });
  const controller = new AbortController();
  const payload = { agent: { session: { append: (type, data) => events.push({ type, data }) } },
    turn: 1, step: 2, provider: 'mock', failure: { code: 'TRANSPORT', message: 'Connection error.' },
    signal: controller.signal };
  return { events, waits, payload, controller, call: () => handler(payload, async () => undefined),
    dispose: () => cleanup() };
}

test('three retries only; new successful step starts a new retry budget', async () => {
  const f = fixture();
  for (let n = 0; n < 3; n++) assert.deepEqual(await f.call(), { kind: 'retry' });
  assert.equal(await f.call(), undefined);
  assert.deepEqual(f.waits, [5000, 15000, 30000]);
  assert.equal(f.events.filter(e => e.type === 'llm/retry-started').length, 3);
  f.payload.step++;
  assert.deepEqual(await f.call(), { kind: 'retry' });
  assert.equal(f.waits[3], 5000);
  await f.dispose();
});

test('only transient failures are retried', async () => {
  for (const code of ['TRANSPORT', 'TIMEOUT', 'RATE_LIMIT', 'SERVER', 'STREAM_CLOSED']) {
    const f = fixture(); f.payload.failure.code = code;
    assert.deepEqual(await f.call(), { kind: 'retry' }); await f.dispose();
  }
  for (const code of ['AUTH', 'INVALID_REQUEST', 'QUOTA_EXCEEDED', 'CONTEXT_WINDOW_EXCEEDED', 'ABORTED']) {
    const f = fixture(); f.payload.failure.code = code;
    assert.equal(await f.call(), undefined); assert.deepEqual(f.waits, []); await f.dispose();
  }
});

test('cancellation and disposal abort active waits', async () => {
  for (const stop of ['cancel', 'dispose']) {
    const f = fixture(waitForRetry);
    const result = f.call();
    if (stop === 'cancel') f.controller.abort();
    else await f.dispose();
    assert.equal(await result, undefined);
    assert.equal(f.events.filter(e => e.type === 'llm/retry-started').length, 0);
    await f.dispose();
  }
});
