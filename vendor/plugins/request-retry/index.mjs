import { randomUUID } from 'node:crypto';

export const name = 'bridge-request-retry';
export const inject = ['agents'];
export const RETRY_DELAYS_MS = Object.freeze([5000, 15000, 30000]);
const RETRYABLE_CODES = new Set(['TRANSPORT', 'TIMEOUT', 'RATE_LIMIT', 'SERVER', 'STREAM_CLOSED']);

export function waitForRetry(milliseconds, signal) {
  if (signal.aborted) return Promise.resolve(false);
  return new Promise(resolve => {
    const timer = setTimeout(() => finish(true), milliseconds);
    function finish(value) {
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
      resolve(value);
    }
    function abort() { finish(false); }
    signal.addEventListener('abort', abort, { once: true });
  });
}

export function apply(ctx, _config = {}, internals = {}) {
  const delay = internals.wait ?? waitForRetry;
  const states = new WeakMap();
  const lifetime = new AbortController();
  const active = new Set();
  const dispose = ctx.on('agent/request-error', (payload, next) => {
    async function recover() {
      const { agent, turn, step, provider, failure, signal } = payload;
      const combined = AbortSignal.any([signal, lifetime.signal]);
      if (combined.aborted) return;
      if (!RETRYABLE_CODES.has(failure.code)) return next();
      const key = JSON.stringify([turn, step, provider]);
      let state = states.get(agent);
      if (!state || state.key !== key) {
        state = { key, count: 0, retryId: randomUUID() };
        states.set(agent, state);
      }
      if (state.count >= RETRY_DELAYS_MS.length) return next();
      const delayMs = RETRY_DELAYS_MS[state.count++];
      const retry = state.count;
      agent.session.append('llm/retry', {
        retryId: state.retryId, turn, step, provider, mode: 'normal',
        policyKey: 'bridge-5-15-30', retry, maxRetries: 3, delayMs, failure,
      });
      if (!await delay(delayMs, combined) || combined.aborted) return;
      agent.session.append('llm/retry-started', { retryId: state.retryId, turn, step, retry });
      return { kind: 'retry' };
    }
    const operation = recover().finally(() => active.delete(operation));
    active.add(operation);
    return operation;
  });
  ctx.effect(() => async () => {
    dispose();
    lifetime.abort();
    await Promise.allSettled([...active]);
  }, 'bridge-request-retry: cancel pending waits');
}
