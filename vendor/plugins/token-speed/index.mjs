import { appendFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';

export const name = 'bridge-token-speed';
export const inject = ['llm'];

// Observe the provider stream without modifying requests, chunks or retry policy.
export function apply(ctx, config = {}, internals = {}) {
  const now = internals.now ?? (() => performance.now());
  const write = internals.write ?? (data => appendFileSync(config.file, JSON.stringify(data) + '\n'));
  ctx.on('llm/stream', async function* (options, next) {
    const id = randomUUID();
    const started = now();
    let first = null, lastUpdate = started, chars = 0, usage = null, finish = 'interrupted', failure = null;
    function report(kind) {
      const elapsed = Math.max(0, (now() - started) / 1000);
      const known = usage && Object.values(usage).some(v => typeof v === 'number' && v > 0);
      const output = known && Number.isFinite(usage.outputTokens) ? usage.outputTokens : null;
      const data = { kind, request_id: id, model: options.model,
        elapsed_seconds: elapsed, first_token_seconds: first, received_characters: chars,
        usage: known ? usage : null, output_tokens: output,
        average_tps: output !== null && elapsed > 0 ? output / elapsed : null,
        finish_reason: finish, failure_code: failure };
      // Monitoring must never interrupt generation (disk full, missing directory, etc.).
      try { write(data); } catch {}
    }
    report('start');
    try {
      for await (const chunk of next()) {
        const text = chunk.type === 'tool-call-delta' ? (chunk.argumentsDelta || chunk.name || '')
          : ['text-delta', 'reasoning-delta'].includes(chunk.type) ? chunk.text : '';
        if (text) {
          chars += [...text].length;
          if (first === null) { first = (now() - started) / 1000; report('progress'); }
          if (now() - lastUpdate >= 1000) { lastUpdate = now(); report('progress'); }
        }
        if (chunk.type === 'usage') usage = chunk.usage;
        if (chunk.type === 'finish') { finish = chunk.reason.kind; failure = chunk.reason.failure?.code ?? null; }
        yield chunk;
      }
    } catch (error) {
      finish = 'error';
      failure = error?.failure?.code ?? error?.code ?? null;
      throw error;
    } finally { report('end'); }
  });
}
