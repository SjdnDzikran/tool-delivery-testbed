/**
 * Read-only request observer for verification runs [ours].
 *
 * Registers the documented `before_provider_request` extension hook
 * (extensions/types.ts, dispatched in the pinned 1.0.4 session runtime as
 * `transformProviderPayload`) and writes a sanitized copy of the outbound
 * provider payload plus a hash of the exact bytes seen. The handler returns
 * undefined: the pinned runner only replaces the payload when a handler
 * result is !== undefined, so observation does not modify the request.
 * The event carries the payload only — never headers, so provider
 * credentials are structurally unreachable here.
 *
 * Env:
 *   PI_OBSERVER_DIR      (required) sanitized payload output dir
 *   PI_OBSERVER_RAW_DIR  (optional) full raw payload dir (private, /tmp)
 *
 * Thinking blocks are redacted (length kept); no auth material exists in
 * the payload. Raw copies stay outside the repository.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import * as crypto from "node:crypto";

export default function (pi) {
  const outDir = process.env.PI_OBSERVER_DIR;
  if (!outDir) return; // no-op when unset (never alters the run)
  const rawDir = process.env.PI_OBSERVER_RAW_DIR || "";
  fs.mkdirSync(outDir, { recursive: true });
  if (rawDir) fs.mkdirSync(rawDir, { recursive: true });
  let n = 0;

  const redactMessages = (messages) =>
    (Array.isArray(messages) ? messages : []).map((m) => {
      const out = { role: m.role };
      if (typeof m.content === "string") {
        out.content = m.content.length > 2000
          ? m.content.slice(0, 2000) + `…[${m.content.length} chars total]`
          : m.content;
      } else {
        out.content = (Array.isArray(m.content) ? m.content : []).map((b) => {
          if (b && (b.type === "thinking" || b.type === "reasoning")) {
            const text = typeof b.text === "string" ? b.text : "";
            return { type: b.type, redacted: true, charLength: text.length };
          }
          if (b && b.type === "text" && typeof b.text === "string" && b.text.length > 2000) {
            return { ...b, text: b.text.slice(0, 2000) + `…[${b.text.length} chars total]` };
          }
          return b;
        });
      }
      if (typeof m.reasoning_content === "string") {
        out.reasoning_content_redacted = {
          charLength: m.reasoning_content.length,
        };
      }
      if (Array.isArray(m.tool_calls)) {
        out.tool_calls = m.tool_calls.map((tc) => ({
          id: tc.id,
          type: tc.type,
          function: {
            name: tc.function?.name,
            arguments:
              typeof tc.function?.arguments === "string" &&
              tc.function.arguments.length > 2000
                ? tc.function.arguments.slice(0, 2000) +
                  `…[${tc.function.arguments.length} chars total]`
                : tc.function?.arguments,
          },
        }));
      }
      if (m.tool_call_id !== undefined) out.tool_call_id = m.tool_call_id;
      if (m.name !== undefined) out.name = m.name;
      return out;
    });

  pi.on("before_provider_request", async (event) => {
    n += 1;
    const payload = event.payload;
    const rawText = JSON.stringify(payload);
    const rawHash = crypto.createHash("sha256").update(rawText).digest("hex");
    if (rawDir) {
      fs.writeFileSync(path.join(rawDir, `payload-${String(n).padStart(3, "0")}.json`), rawText);
    }
    let sanitized = payload;
    if (payload && typeof payload === "object") {
      sanitized = { ...payload };
      for (const key of Object.keys(sanitized)) {
        if (/messages|input|system|prompt/i.test(key)) {
          const val = sanitized[key];
          if (Array.isArray(val)) sanitized[key] = redactMessages(val);
          else if (typeof val === "string" && val.length > 4000) {
            sanitized[key] = val.slice(0, 4000) + `…[${val.length} chars total]`;
          }
        }
      }
    }
    const record = {
      observer: "pi-request-observer",
      hook: "before_provider_request",
      index: n,
      timestamp_utc: new Date().toISOString(),
      payload_sha256: "sha256:" + rawHash,
      payload_bytes: Buffer.byteLength(rawText),
      payload_top_level_keys: payload && typeof payload === "object" ? Object.keys(payload) : null,
      sanitized_payload: sanitized,
    };
    fs.writeFileSync(
      path.join(outDir, `payload-${String(n).padStart(3, "0")}.sanitized.json`),
      JSON.stringify(record, null, 2));
    return undefined; // read-only: pinned runner keeps original payload
  });
}
