import assert from 'node:assert/strict';
import { apply } from '../vendor/plugins/token-speed/index.mjs';
import { readFile } from 'node:fs/promises';

let handler, clock = 0;
const records = [];
apply({ on(event, fn) { assert.equal(event, 'llm/stream'); handler = fn; } }, {},
  { now: () => clock, write: data => records.push(data) });
async function* stream() {
  clock = 2000; yield { type: 'text-delta', text: 'A中', index: 0 };
  clock = 4000; yield { type: 'text-delta', text: 'B', index: 0 };
  clock = 5000; yield { type: 'usage', usage: { inputTokens: 200, outputTokens: 120, reasoningTokens: 20 } };
  yield { type: 'finish', reason: { kind: 'stop' } };
}
const chunks = [];
for await (const chunk of handler({ model: 'test' }, stream)) chunks.push(chunk);
assert.equal(chunks.length, 4);
assert.equal(records.at(-1).average_tps, 24); // Reasoning is a subset, never added twice.
assert.equal(records.at(-1).first_token_seconds, 2);
assert.equal(records.at(-1).received_characters, 3);
assert.equal(records[0].average_tps, null);
clock = 6000;
async function* missing() { clock = 7000; yield { type: 'finish', reason: { kind: 'error', failure: {code: 'TIMEOUT'} } }; }
for await (const chunk of handler({ model: 'test' }, missing)) {}
assert.equal(records.at(-1).output_tokens, null);
assert.equal(records.at(-1).average_tps, null);
assert.equal(records.at(-1).failure_code, 'TIMEOUT');
async function* broken() { clock += 1000; throw new Error('upstream failed'); }
await assert.rejects(async () => { for await (const chunk of handler({ model: 'test' }, broken)) {} }, /upstream failed/);
assert.equal(records.at(-1).finish_reason, 'error');
let pass;
apply({on(_event, fn) {pass=fn;}}, {}, {now:()=>clock, write() {throw new Error('disk full');}});
for await (const chunk of pass({model:'test'}, missing)) {}
const formatSource = await readFile(new URL('../web/lib/token_speed_format.js', import.meta.url), 'utf8');
const { formatTokenSpeed } = await import(`data:text/javascript;base64,${Buffer.from(formatSource).toString('base64')}`);
const text = formatTokenSpeed({requests: [records.at(-1)], status:'error', task_seconds: 8, usage_complete: false, model:'test'});
assert.ok(text.includes('未返回token用量'));
assert.ok(text.includes('已停止'));
assert.ok(!text.includes('NaN'));
console.log('TOKEN_SPEED_STREAM_TIMING_MISSING_USAGE_FAILURE_PASSTHROUGH_OK');
