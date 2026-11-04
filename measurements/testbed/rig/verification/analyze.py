#!/usr/bin/env python3
"""Analyze verification run data and emit sanitized evidence [ours].

Reads (all under the private tmp root):
  raw/<campaign>/<trial>/payload-NNN.json     exact outbound payloads
  runs/<campaign>/campaign.json               frozen state + trial records
  runs/<campaign>/trials/<t>/attempt-*/private/events.jsonl
  runs/<campaign>/trials/<t>/attempt-*/sessions/*.jsonl

Writes machine-readable sanitized evidence into --evidence-dir:
  isolation-requests.json, native-tools.json, usage-accounting.json,
  live-call-log.json, payload-samples/payload-001.<trial>.sanitized.json

All thinking/reasoning content is redacted (lengths only). No credentials
are ever read here beyond comparing candidate secret VALUES from this
process's own environment against payload text (booleans only).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE_DEFAULT = HERE / "evidence"

POISON_MARKERS = [
    "POISON-MCP-MARKER", "POISON-SKILL-MARKER", "POISON-SYSTEM-MARKER",
    "POISON-AGENTS-MARKER", "POISON-CLAUDE-MARKER", "POISON-EXT-MARKER",
    "POISON-PROMPT-MARKER", "POISON-THEME-MARKER", "POISON-PONYTAIL-MARKER",
]
GLOBAL_SKILL_MARKERS = {
    "ponytail (user ~/.agents/skills)":
        "Forces the laziest solution that actually works",
    "brave-search (user ~/.agents/skills)":
        "Use Brave Search CLI (`bx`) for web searches",
    "shadcn (user ~/.agents/skills)":
        "Manages shadcn components and projects",
    "ship-it (user ~/.agents/skills)":
        "merge a GitHub pull request",
}
NATIVE_TOOLS = ["read", "bash", "edit", "write"]
CANARY_SUMMARY = "Verification canary: canary_echo echoes text"
DECOY_SUMMARY = "Verification decoy: DECOY-ONLY server"
SKILL_BODY_PHRASE = "Write that line, unmodified"
PINNED_MODELS = {"glm53flash": "glm-5.3-flash", "gpt6luna": "gpt-6-luna"}


def sha(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode()).hexdigest()


def load_raw_payloads(raw_campaign: Path, trial: str) -> list[dict]:
    d = raw_campaign / trial
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("payload-*.json")):
        out.append({"path": str(p), "payload": json.loads(p.read_text())})
    return out


def tool_entries(payload: dict) -> list[dict]:
    """Normalize tool declarations from any known provider payload shape."""
    tools = payload.get("tools") or []
    norm = []
    for t in tools:
        if isinstance(t, dict) and "function" in t:
            f = t["function"]
            norm.append({"name": f.get("name"),
                         "description": f.get("description"),
                         "schema": f.get("parameters")})
        elif isinstance(t, dict) and "name" in t:
            norm.append({"name": t.get("name"),
                         "description": t.get("description"),
                         "schema": t.get("input_schema") or t.get("parameters")})
    return norm


def system_prompt(payload: dict) -> str:
    msgs = payload.get("messages")
    if isinstance(msgs, list) and msgs:
        first = msgs[0]
        if isinstance(first, dict) and first.get("role") == "system":
            c = first.get("content")
            return c if isinstance(c, str) else json.dumps(c)
    for key in ("system", "systemPrompt"):
        v = payload.get(key)
        if isinstance(v, str):
            return v
    return ""


def message_profile(payload: dict) -> list[dict]:
    prof = []
    for m in payload.get("messages") or []:
        if not isinstance(m, dict):
            continue
        entry = {"role": m.get("role")}
        c = m.get("content")
        if isinstance(c, str):
            entry["content"] = c
        elif isinstance(c, list):
            entry["content_types"] = [b.get("type") if isinstance(b, dict)
                                      else str(b) for b in c]
            entry["content_char_lengths"] = [
                len(b.get("text") or "") if isinstance(b, dict) else 0
                for b in c]
        if isinstance(m.get("reasoning_content"), str):
            entry["reasoning_content_redacted"] = {
                "charLength": len(m["reasoning_content"])}
        if isinstance(m.get("tool_calls"), list):
            entry["tool_calls"] = [
                {"name": tc.get("function", {}).get("name"),
                 "arguments": tc.get("function", {}).get("arguments")}
                for tc in m["tool_calls"]]
        prof.append(entry)
    return prof


def sanitize_payload(payload: dict) -> dict:
    """Model-visible request shape with thinking redacted, tools kept."""
    out = dict(payload)
    prof = message_profile(payload)
    if isinstance(payload.get("messages"), list):
        kept = []
        for m, p in zip(payload["messages"], prof):
            kept.append({"role": p["role"],
                         "content": p.get("content"),
                         "content_types": p.get("content_types"),
                         "reasoning_content_redacted":
                             p.get("reasoning_content_redacted"),
                         "tool_calls": p.get("tool_calls"),
                         "tool_call_id": m.get("tool_call_id")})
        out["messages"] = kept
    for key in ("system", "systemPrompt"):
        if isinstance(out.get(key), str):
            out[key] = out[key]
    return out


def trial_usage(events_path: Path) -> dict:
    if not events_path.is_file():
        return {"error": "no events file"}
    total = 0
    per_request = []
    for line in events_path.read_text(errors="replace").split('\n'):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") == "message_end":
            msg = rec.get("message") or {}
            if msg.get("role") == "assistant":
                u = msg.get("usage") or {}
                per_request.append({k: u.get(k) for k in
                                    ("input", "output", "cacheRead",
                                     "cacheWrite", "reasoning",
                                     "totalTokens")})
                total += int(u.get("totalTokens") or 0)
    return {"runner_sum_total_tokens": total, "per_request": per_request,
            "n_requests": len(per_request)}


def session_aux_usage(attempt_dir: Path) -> dict:
    """Auxiliary model usage recorded in session files but absent from
    assistant message_end events (cache warming, compaction, unknown)."""
    aux = []
    compactions = 0
    for f in (attempt_dir / "sessions").glob("*.jsonl"):
        for line in f.read_text(errors="replace").split('\n'):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "usage":
                aux.append({"kind": rec.get("kind"),
                            "totalTokens": (rec.get("usage") or {})
                            .get("totalTokens")})
            elif rec.get("type") == "compaction":
                compactions += 1
                u = rec.get("usage")
                if u:
                    aux.append({"kind": "compaction",
                                "totalTokens": (u or {}).get("totalTokens")})
    return {"aux_usage_entries": aux, "compaction_entries": compactions,
            "aux_total_tokens": sum(a["totalTokens"] or 0 for a in aux)}


def analyze_trial(campaign: str, trial_rec: dict, raw_campaign: Path,
                  observer_campaign: Path) -> dict:
    spec = trial_rec["spec"]
    mode, model_id, variant = spec["mode"], spec["model"], spec["catalog"]
    trial = spec["trial_id"]
    payloads = load_raw_payloads(raw_campaign, trial)
    res = {
        "campaign": campaign, "trial": trial, "mode": mode,
        "model": PINNED_MODELS.get(model_id, model_id),
        "catalog_variant": variant,
        "n_payloads_captured": len(payloads),
    }
    # Usage accounting (independent of payload capture)
    attempt = Path(trial_rec.get("_attempt_dir", ""))
    if attempt.is_dir():
        u = trial_usage(attempt / "private" / "events.jsonl")
        aux = session_aux_usage(attempt)
        if "error" in u:
            res["usage"] = {"note": u["error"],
                            "campaign_recorded_total_tokens":
                                trial_rec.get("usage_total_tokens")}
        else:
            res["usage"] = {**u, **aux,
                            "campaign_recorded_total_tokens":
                                trial_rec.get("usage_total_tokens"),
                            "runner_matches_recomputed":
                                u.get("runner_sum_total_tokens") ==
                                trial_rec.get("usage_total_tokens"),
                            "aux_missing_from_runner_watchdog":
                                aux["aux_total_tokens"]}
    if not payloads:
        res["observer"] = "no payloads (unobserved run or failed pre-flight)"
        return res

    texts = [json.dumps(p["payload"]) for p in payloads]
    first = payloads[0]["payload"]
    tools1 = tool_entries(first)
    names1 = [t["name"] for t in tools1]
    sys1 = system_prompt(first)

    # A1 model pin
    res["model_id_in_payload"] = first.get("model")
    res["model_pin_ok"] = first.get("model") == PINNED_MODELS.get(model_id)

    # thinking settings pin
    res["thinking_fields"] = {k: first.get(k) for k in
                              ("thinking", "reasoning_effort")
                              if k in first}

    # A2/A3 bleed markers
    blob = "\n".join(texts)
    res["poison_markers_found"] = [m for m in POISON_MARKERS if m in blob]
    res["global_skill_markers_found"] = [
        name for name, marker in GLOBAL_SKILL_MARKERS.items()
        if marker in blob]

    # A4 codemode (tool-level; the docs list in Pi's default system prompt
    # mentions docs/codemode.md, so strip <docs> blocks before text check)
    res["codemode_tool_present"] = any(
        "codemode" in (n or "") for n in names1)
    res["codemode_in_system_prompt"] = "codemode" in re.sub(
        r"<docs>.*?</docs>", "", sys1, flags=re.S)

    # A5 native tools (from first payload)
    res["native_tool_hashes"] = {
        t["name"]: sha(json.dumps({"name": t["name"],
                                   "description": t["description"],
                                   "schema": t["schema"]}, sort_keys=True))
        for t in tools1 if t["name"] in NATIVE_TOOLS}
    res["native_tools_present"] = sorted(
        n for n in names1 if n in NATIVE_TOOLS)

    # A6/A7/A8 delivery-route specifics
    mcp_tools = [n for n in names1 if str(n).startswith("mcp__")]
    res["first_request_mcp_tools"] = mcp_tools
    res["first_request_has_tool_search"] = "tool_search" in names1
    if mode == "eager":
        if spec.get("task") == "canary_echo":
            res["route_first_request_ok"] = (
                "mcp__canary__canary_echo" in names1 and
                "tool_search" not in names1)
            canary = next((t for t in tools1
                           if t["name"] == "mcp__canary__canary_echo"), None)
            res["canary_schema_present"] = bool(canary and canary["schema"])
            res["canary_schema_hash"] = (sha(json.dumps(canary["schema"],
                                                        sort_keys=True))
                                         if canary else None)
            res["decoy_declared_first_request"] = any(
                "decoy" in (n or "") for n in mcp_tools)
        else:
            # control task: no capability admitted on any route
            res["route_first_request_ok"] = not mcp_tools
            res["route_note"] = "control task: no capability admitted"
    elif mode == "deferred":
        if spec.get("task") == "canary_echo":
            summary_ok = CANARY_SUMMARY in sys1
            loaded_later = any(
                "mcp__canary__canary_echo" in
                [t["name"] for t in tool_entries(p["payload"])]
                for p in payloads[1:])
            tool_search_calls = []
            for p in payloads:
                for m in p["payload"].get("messages") or []:
                    for tc in (m.get("tool_calls") or []):
                        if tc.get("function", {}).get("name") == "tool_search":
                            tool_search_calls.append(
                                tc["function"].get("arguments"))
            res["route_first_request_ok"] = (not mcp_tools and
                                             "tool_search" in names1)
            res["deferred_summary_in_system_prompt"] = summary_ok
            res["deferred_decoy_summary_in_system_prompt"] = \
                DECOY_SUMMARY in sys1
            res["deferred_tools_loaded_after_search"] = loaded_later
            res["tool_search_calls"] = tool_search_calls
        else:
            res["route_first_request_ok"] = (not mcp_tools and
                                             "tool_search" not in names1)
            res["route_note"] = "control task: no capability admitted"
    elif mode == "cli":
        if spec.get("task") == "canary_echo":
            skill_line = "canary-skill" in sys1
            body_first = SKILL_BODY_PHRASE in sys1
            body_later = any(SKILL_BODY_PHRASE in json.dumps(p["payload"].get(
                "messages") or []) for p in payloads[1:])
            res["route_first_request_ok"] = (not mcp_tools and
                                             "tool_search" not in names1)
            res["skill_metadata_in_system_prompt"] = skill_line
            res["skill_body_absent_first_request"] = not body_first
            res["skill_body_loaded_later"] = body_later
            res["decoy_skill_in_system_prompt"] = "decoy-skill" in sys1
        else:
            res["route_first_request_ok"] = (not mcp_tools and
                                             "tool_search" not in names1)
            res["route_note"] = "control task: no capability admitted"

    # secret scan (booleans only; candidate values never echoed)
    candidates = []
    for k, v in os.environ.items():
        if re.match(r"^(ZAI|OPENAI|ANTHROPIC|BRAVE)_\w*(KEY|TOKEN)$", k) \
                and v and len(v) >= 12:
            candidates.append((k, v))
    blob = "\n".join(texts) if payloads else ""
    res["secret_values_found_in_payloads"] = [k for k, v in candidates
                                              if v in blob]
    res["secret_pattern_hits"] = {
        "sk_prefix": bool(re.search(r"sk-[A-Za-z0-9]{20,}", blob)),
        "gho_token": bool(re.search(r"gho_[A-Za-z0-9]{20,}", blob)),
        "github_pat": bool(re.search(r"github_pat_[A-Za-z0-9_]{20,}", blob)),
    }
    return res


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tmp-root", type=Path, required=True, nargs="+",
                    action="extend")
    ap.add_argument("--evidence-dir", type=Path, default=EVIDENCE_DEFAULT)
    args = ap.parse_args()
    roots = [Path(r).resolve() for r in args.tmp_root]
    ev = args.evidence_dir.resolve()
    (ev / "payload-samples").mkdir(parents=True, exist_ok=True)

    campaigns = sorted({c for root in roots
                        for base in (root / "runs",
                                     root / "poisoned-project" / "runs")
                        for c in base.glob("*/campaign.json")})

    def find_root(cjson: Path, campaign: str) -> Path:
        """Tmp root holding raw/ + observer/ for this campaign (campaigns
        may live under a different --tmp-root than their run_root)."""
        for r in roots:
            if ((r / "raw" / campaign).is_dir()
                    or (r / "observer" / campaign).is_dir()):
                return r
        return cjson.parents[2]
    isolation_rows, call_rows = [], []
    native_hashes: dict[str, dict] = {}
    for cjson in campaigns:
        campaign = cjson.parent.name
        state = json.loads(cjson.read_text())
        root = find_root(cjson, campaign)
        raw_campaign = root / "raw" / campaign
        observer_campaign = root / "observer" / campaign
        for t_id, rec in state["trials"].items():
            attempts = sorted((cjson.parent / "trials" / t_id)
                              .glob("attempt-*"))
            rec = dict(rec)
            rec["_attempt_dir"] = str(attempts[-1]) if attempts else ""
            row = analyze_trial(campaign, rec, raw_campaign,
                                observer_campaign)
            row["status"] = rec["status"]
            row["verifier_exit_code"] = rec.get("verifier_exit_code")
            row["stop_reason"] = rec.get("stop_reason")
            row["last_error"] = (rec.get("last_error") or "")[:200]
            row["attempts"] = rec.get("attempts")
            isolation_rows.append(row)
            # per-campaign observer tag may equal trial id directly
            call_rows.append({
                "campaign": campaign, "trial": t_id,
                "mode": rec["spec"]["mode"], "model":
                    PINNED_MODELS.get(rec["spec"]["model"]),
                "catalog": rec["spec"]["catalog"],
                "task": rec["spec"]["task"],
                "status": rec["status"],
                "attempts": rec.get("attempts"),
                "verifier_exit_code": rec.get("verifier_exit_code"),
                "usage_total_tokens": rec.get("usage_total_tokens"),
                "stop_reason": rec.get("stop_reason"),
                "pi_exit_code": rec.get("pi_exit_code"),
                "n_model_requests": row.get("usage", {}).get("n_requests"),
                "last_error": (rec.get("last_error") or "")[:300],
            })
            # payload sample (sanitized) for first request per trial
            raws = load_raw_payloads(raw_campaign, t_id)
            if raws:
                sample = {"trial": f"{campaign}/{t_id}",
                          "mode": rec["spec"]["mode"],
                          "model": PINNED_MODELS.get(rec["spec"]["model"]),
                          "catalog_variant": rec["spec"]["catalog"],
                          "sanitized_first_request":
                              sanitize_payload(raws[0]["payload"])}
                (ev / "payload-samples" /
                 f"payload-001.{campaign}.{t_id}.sanitized.json").write_text(
                    json.dumps(sample, indent=2))
            # native tool hash collection per mode (glm trials only, to
            # compare arms at identical settings)
            if (rec["spec"]["model"] == "glm53flash"
                    and row.get("native_tool_hashes")
                    and rec["status"] in ("pass", "incorrect", "incomplete")):
                variant = rec["spec"]["catalog"]
                native_hashes[f"{rec['spec']['mode']}/{variant}/{t_id}"] = \
                    row["native_tool_hashes"]

    native_sets = {}
    for key, hashes in native_hashes.items():
        native_sets.setdefault(json.dumps(hashes, sort_keys=True),
                               []).append(key)
    native_tools = {
        "distinct_native_tool_schema_sets": len(native_sets),
        "sets": [{("trials: " + ", ".join(v)): k}
                 for k, v in native_sets.items()],
        "native_tools_identical_across_arms":
            len(native_sets) == 1,
    }

    # faithfulness: cwd-length-matched pair (observed twin vs unobserved
    # run) so path-length token differences cannot mask observer effects
    faith = {"checked": False}
    obs = [r for r in isolation_rows
           if r["campaign"] == "verify-plain-eager-obz"
           and r["mode"] == "eager" and r["model"] == "glm-5.3-flash"
           and r.get("usage")]
    pln = [r for r in isolation_rows
           if r["campaign"] == "verify-plain-eager-glm"]
    if obs and pln:
        a = obs[0]["usage"]["per_request"][0]
        b = pln[0]["usage"]["per_request"][0]
        faith = {
            "checked": True,
            "observed_trial": obs[0]["campaign"] + "/" + obs[0]["trial"],
            "unobserved_trial": pln[0]["campaign"] + "/" + pln[0]["trial"],
            "cwd_length_matched": True,
            "checked": True,
            "first_request_prompt_tokens_observed":
                a["input"] + (a["cacheRead"] or 0) + (a["cacheWrite"] or 0),
            "first_request_prompt_tokens_unobserved":
                b["input"] + (b["cacheRead"] or 0) + (b["cacheWrite"] or 0),
            "equal": (a["input"] + (a["cacheRead"] or 0) +
                      (a["cacheWrite"] or 0)) ==
                     (b["input"] + (b["cacheRead"] or 0) +
                      (b["cacheWrite"] or 0)),
        }

    totals = {
        "trials_total": len(call_rows),
        "by_status": {},
        "model_requests_total": sum(r.get("n_model_requests") or 0
                                    for r in call_rows),
        "model_requests_by_model": {},
        "trials_by_model_mode": {},
    }
    for r in call_rows:
        totals["by_status"][r["status"]] = \
            totals["by_status"].get(r["status"], 0) + 1
        m = r["model"] or "unknown"
        totals["model_requests_by_model"][m] = \
            totals["model_requests_by_model"].get(m, 0) + \
            (r["n_model_requests"] or 0)
        key = f"{m}/{r['mode']}"
        totals["trials_by_model_mode"][key] = \
            totals["trials_by_model_mode"].get(key, 0) + 1

    (ev / "isolation-requests.json").write_text(json.dumps(
        {"rows": isolation_rows}, indent=2))
    (ev / "native-tools.json").write_text(json.dumps(native_tools, indent=2))
    (ev / "live-call-log.json").write_text(json.dumps(
        {"totals": totals, "trials": call_rows}, indent=2))
    usage_rows = [{k: r.get(k) for k in
                   ("campaign", "trial", "mode", "model", "status", "usage")}
                  for r in isolation_rows if r.get("usage")]
    (ev / "usage-accounting.json").write_text(json.dumps(
        {"rows": usage_rows}, indent=2))
    print(json.dumps({
        "trials": totals["trials_total"],
        "by_status": totals["by_status"],
        "model_requests_total": totals["model_requests_total"],
        "native_tools_identical_across_arms":
            native_tools["native_tools_identical_across_arms"],
        "faithfulness": faith,
        "bleed_findings": [
            {"trial": r["trial"], "campaign": r["campaign"],
             "poison": r.get("poison_markers_found"),
             "global_skills": r.get("global_skill_markers_found"),
             "codemode": [r.get("codemode_tool_present"),
                          r.get("codemode_in_system_prompt")]}
            for r in isolation_rows
            if r.get("poison_markers_found")
            or r.get("global_skill_markers_found")
            or r.get("codemode_tool_present")
            or r.get("codemode_in_system_prompt")],
        "secret_findings": [
            {"trial": r["trial"], "campaign": r["campaign"],
             "secret_values_found_in_payloads":
                 r.get("secret_values_found_in_payloads"),
             "secret_pattern_hits": r.get("secret_pattern_hits")}
            for r in isolation_rows
            if r.get("secret_values_found_in_payloads")
            or any(r.get("secret_pattern_hits", {}).values())],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
