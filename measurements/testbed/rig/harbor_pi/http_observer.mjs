// Passive capture of selected native SDK inference requests, including compaction.
// Install as a Pi extension AFTER its HTTP dispatcher setup. Never inspect headers
// or consume response bodies. A Node preload is overwritten by undici.install().
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const marker = Symbol.for('pi-study-http-observer');
let sequence = 0;
export function installHttpObserver(directory = process.env.PI_HTTP_OBSERVER_DIR) {
  const original = globalThis.fetch;
  if (!directory || typeof original !== 'function' || original[marker]) return;
  globalThis.fetch = async function (...args) {
    let file, record;
    const save = () => {
      if (file) fs.writeFileSync(file, JSON.stringify(record), { mode: 0o600 });
    };
    try {
      const [input, options] = args;
      const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
      if (['api.openai.com', 'chatgpt.com', 'api.z.ai'].includes(url.hostname)
          && /\/(?:responses|chat\/completions)$/.test(url.pathname)
          && typeof options?.body === 'string') {
        const payload = JSON.parse(options.body);
        fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
        file = path.join(directory, `${process.pid}-${String(++sequence).padStart(4, '0')}-${crypto.randomUUID()}.json`);
        record = { observer: 'native-sdk-fetch-v1', pid: process.pid,
          started_utc: new Date().toISOString(), endpoint: url.origin + url.pathname,
          payload_sha256: crypto.createHash('sha256').update(options.body).digest('hex'),
          payload, status: 'started' };
        save();
      }
    } catch {
      // Preserve SDK behavior; accounting validation must reject missing capture.
      fs.writeSync(2, 'HTTP observer capture failed; coverage is incomplete\n');
    }
    try {
      const response = await Reflect.apply(original, this, args);
      if (record) {
        record.status = 'response_headers';
        record.http_status = response.status;
        record.finished_headers_utc = new Date().toISOString();
        try { save(); } catch { fs.writeSync(2, 'HTTP observer metadata write failed\n'); }
      }
      return response;
    } catch (error) {
      if (record) {
        record.status = 'transport_error';
        record.error_name = error?.name;
        try { save(); } catch { /* native error remains authoritative */ }
      }
      throw error;
    }
  };
  Object.defineProperty(globalThis.fetch, marker, { value: true });
}

export default function (pi) {
  pi.on('before_agent_start', () => { installHttpObserver(); });
}
