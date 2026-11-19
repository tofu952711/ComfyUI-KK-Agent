import { appendFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

export const name = 'bridge-exact-inputs';
export const inject = ['systemPrompt'];

// A complete literal section replaces Harness persona and generic advice.
// Tool schemas and actual media remain available independently of this text.
export function apply(ctx, config = {}) {
  if (typeof config.text !== 'string' || !config.text.trim()) {
    throw new Error('The second text input must contain system instructions');
  }
  ctx.systemPrompt.section({
    name: 'bridge:exact-system-input', order: 0,
    text: config.text, interpolate: false, complete: true,
  });
  ctx.systemPrompt.suppressRuntimeContext();
  // Providers add attachment handles and mandatory runtime notices after
  // system-prompt assembly. Project the outgoing JSON at the provider boundary
  // so these notices cannot leak into the two-textbox path. This runtime is
  // private to one node run; only its configured inference endpoint is matched.
  const previous = globalThis.fetch;
  const base = config.baseURL.replace(/\/$/, '').replace(/\/(?:chat\/completions|responses)$/, '');
  const endpoints = new Set([base + '/chat/completions', base + '/responses', base + '/messages', base + '/v1/messages']);
  globalThis.fetch = async function (input, init) {
    const url = typeof input === 'string' || input instanceof URL ? String(input) : input.url;
    const method = init?.method ?? (input instanceof Request ? input.method : 'GET');
    if (method.toUpperCase() !== 'POST') return previous(input, init);
    if (!endpoints.has(url)) {
      // Record only an endpoint mismatch, never headers, credentials or bodies.
      if (new URL(url).origin === new URL(base).origin &&
          /\/(?:chat\/completions|responses|messages)\/?$/.test(new URL(url).pathname)) {
        audit(config, { stage: 'unmatched_endpoint', path: new URL(url).pathname });
      }
      return previous(input, init);
    }
    const raw = init?.body ?? (input instanceof Request ? await input.clone().text() : null);
    if (raw == null) return previous(input, init);
    const payload = JSON.parse(typeof raw === 'string' ? raw : Buffer.from(raw).toString('utf8'));
    const projected = projectPayload(payload, config.text, config.user, config.instructionRole, config.mediaEvidence);
    audit(config, { stage: 'outgoing_request', path: new URL(url).pathname,
      ...payloadSummary(projected, config.text, config.user, config.mediaEvidence) });
    const body = JSON.stringify(projected);
    if (input instanceof Request) return previous(new Request(input, { ...init, body }));
    return previous(input, { ...init, body });
  };
  ctx.effect(() => () => { globalThis.fetch = previous; });
}

export function projectPayload(payload, system, user, instructionRole = 'system', mediaEvidence = '') {
  if (Array.isArray(payload.input)) {
    let suppliedUser = false;
    const input = [];
    for (const item of payload.input) {
      if (item.role === 'system' || item.role === 'developer') continue;
      // Reasoning replay, function calls and function outputs are protocol items.
      if (item.role !== 'user') { input.push(item); continue; }
      if (suppliedUser) {
        // Also accept adapters that carry tool images in a separate user
        // message. Native function_call_output media passes through unchanged.
        const images = Array.isArray(item.content)
          ? item.content.filter(block => block.type === 'input_image') : [];
        if (images.length && input.some(previous => previous.type === 'function_call_output')) {
          input.push({ ...item, content: images });
        }
        continue;
      }
      suppliedUser = true;
      const blocks = typeof item.content === 'string' ? [] : (item.content ?? []);
      input.push({ ...item, content: [
        { type: 'input_text', text: user },
        ...(mediaEvidence ? [{ type: 'input_text', text: mediaEvidence }] : []),
        ...blocks.filter(block => !['text', 'input_text'].includes(block.type)),
      ] });
    }
    if (!suppliedUser) throw new Error('Missing original user input');
    return { ...payload, instructions: system, input };
  }
  const messages = [];
  let suppliedUser = false;
  const anthropic = 'system' in payload;
  if (!['system', 'developer'].includes(instructionRole)) throw new Error('Invalid instruction role');
  if (!anthropic) messages.push({ role: instructionRole, content: system });
  for (const message of payload.messages) {
    if (message.role === 'system' || message.role === 'developer') continue;
    if (message.role !== 'user') { messages.push(message); continue; }
    const blocks = typeof message.content === 'string'
      ? [{ type: 'text', text: message.content }] : message.content;
    const results = blocks.filter(block => block.type === 'tool_result');
    if (results.length) { messages.push({ ...message, content: results }); continue; }
    if (suppliedUser) continue;
    suppliedUser = true;
    messages.push({ ...message, content: [
      { type: 'text', text: user },
      ...(mediaEvidence ? [{ type: 'text', text: mediaEvidence }] : []),
      ...blocks.filter(block => block.type !== 'text'),
    ] });
  }
  if (!suppliedUser) throw new Error('Missing original user input');
  return { ...payload, ...(anthropic ? { system } : {}), messages };
}

function audit(config, record) {
  if (!config.auditFile) return;
  // Local metadata only. Diagnostics must not interrupt a model request.
  try { appendFileSync(config.auditFile, JSON.stringify({ time: new Date().toISOString(), ...record }) + '\n'); } catch {}
}

export function payloadSummary(payload, system, user, mediaEvidence = '') {
  const responses = Array.isArray(payload.input);
  const messages = responses ? payload.input : payload.messages;
  const anthropic = 'system' in payload;
  const text = content => typeof content === 'string' ? content
    : (content ?? []).filter(b => ['text', 'input_text'].includes(b.type)).map(b => b.text).join('');
  const systems = responses ? [payload.instructions ?? ''] : anthropic ? [text(payload.system)]
    : messages.filter(m => m.role === 'system' || m.role === 'developer').map(m => text(m.content));
  const firstUser = messages.find(m => m.role === 'user' &&
    !(Array.isArray(m.content) && m.content.some(b => b.type === 'tool_result')));
  const userTexts = typeof firstUser?.content === 'string' ? [firstUser.content]
    : (firstUser?.content ?? []).filter(b => ['text', 'input_text'].includes(b.type)).map(b => b.text);
  const userText = userTexts[0] ?? '';
  const evidenceText = userTexts[1] ?? '';
  const systemText = systems.join('');
  const hash = value => createHash('sha256').update(value, 'utf8').digest('hex');
  return { api_format: responses ? 'responses' : anthropic ? 'messages' : 'chat_completions',
    reasoning_effort: responses ? payload.reasoning?.effort ?? null : payload.reasoning_effort ?? payload.output_config?.effort ?? null,
    instruction_role: responses ? 'instructions' : anthropic ? 'system' : messages.find(m => m.role === 'system' || m.role === 'developer')?.role,
    system_characters: [...systemText].length, system_sha256: hash(systemText),
    system_exact: systems.length === 1 && systemText === system,
    user_characters: [...userText].length, user_sha256: hash(userText), user_exact: !!firstUser && userText === user,
    media_evidence_characters: [...evidenceText].length, media_evidence_sha256: hash(evidenceText),
    media_evidence_exact: evidenceText === mediaEvidence && userTexts.length === (mediaEvidence ? 2 : 1),
    initial_image_blocks: Array.isArray(firstUser?.content)
      ? firstUser.content.filter(b => ['image', 'image_url', 'input_image'].includes(b.type)).length : 0,
    message_count: messages.length, tool_definitions: payload.tools?.length ?? 0 };
}
