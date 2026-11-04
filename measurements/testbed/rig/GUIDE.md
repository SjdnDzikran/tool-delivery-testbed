# Runner guide: schema, semantics, isolation evidence, limits [ours]

Detailed companion to [README.md](README.md). Flag behavior was checked
against the pinned Pi 1.0.4 distribution and its documentation, including
`dist/cli/args.js`, `dist/core/resource-loader.js`,
`dist/extensions/mcp/index.js`, and `dist/core/model-runtime.js`.

## 1. Why the runner exists

The 2026-10-27 draft `run-trial.sh` had four flaws, all confirmed in the
pinned sources:

1. `--no-extensions` disables the built-in MCP extension too, so the MCP
   arms lost `mcp.json` entirely unless `-e builtin:mcp` is passed
   explicitly (`cli.md`, `settings.md`, `resource-loader.js:405`).
2. Deferred exposure is unreachable without the `tool_search` tool: the MCP
   extension activates `tool_search` only if such a tool is registered
   (`extensions/mcp/index.js`, `ensureDiscoveryActive`), and
   `--no-extensions` suppresses `builtin:tool-search`. The deferred arm must
   load `-e builtin:mcp -e builtin:tool-search`.
3. `--no-mcp` maps to `disabledBuiltinExtensions: ["mcp"]`
   (`dist/main.js:634`), which filters even explicit `-e builtin:mcp` — the
   two flags must never be combined. The CLI arm uses `--no-mcp` plus
   explicit `--skill` paths; `--no-skills` only disables discovery, explicit
   `--skill` paths still load (`resource-loader.js:420`).
4. `--no-session` produced ephemeral sessions, defeating transcript audit;
   `--mode json` exits 0 even when the final assistant message has
   `stopReason: "error"` (`docs/cli-integration.md`), so classification must
   parse events.

## 2. Manifest schema (versioned, `schema_version = 1`)

| Section | Keys | Notes |
|---|---|---|
| top | `schema_version`, `env_pass_names[]` | allowlist of extra host env vars passed to trials |
| `[harness]` | `campaign_id`, `binary`, `required_version`, `auth_source`, `auth_mode` (`symlink`\|`copy`), `[harness.env]` | `campaign_id` names the frozen campaign dir |
| `[models.<id>]` | `provider`, `id`, `thinking` | explicit provider + exact model id; written to generated `settings.json` and passed as `--provider/--model/--thinking` |
| `[catalog.<server>]` | `command` xor `url`, `args`, `env`, `env_names[]`, `description`, `timeout` | MCP capability definitions; `exposure` is forbidden here (mode-owned) |
| `[capabilities.<id>]` | `kind = "cli"`, `skills[]`, `executables[]`, `env_names[]` | CLI-arm skill bundles + required executables/env |
| `[tasks.<id>]` | `instruction`, `capabilities[]`, `catalog[]`, `deadline_s`, `setup`, `reset`, `verify`, `verify_timeout_s`, `setup_timeout_s`, `artifacts` | `setup`/`reset`/`verify` are argument arrays; `{workspace}`, `{artifacts}`, `{manifest_dir}`, `{rig_dir}` placeholders resolve at run time; `deadline_s` is fixed per task across arms |
| `[matrix]` | `modes[]`, `models[]`, `catalogs[]` (`required`\|`full`), `reps`, `seed` | plan = seeded shuffle of (task × catalog variant × mode × model × rep); the catalog axis applies to all modes, including CLI skills and controls |
| `[quota]` | `base_s`, `multiplier`, `cap_s`, `pause_above_s`, `max_attempts_per_trial`, `probe_timeout_s`, `probe_command` | provider-quota backoff policy (§6) |
| `[budget]` | `max_total_tokens` | optional kill switch on verified `usage.totalTokens` sums |

Relative paths in `binary`, `auth_source`, `paths.skills_dir`,
`paths.run_root`, and task `instruction` resolve against the manifest
directory. `[paths]` is optional; defaults are `rig/skills` and
`~/.pi-research-runs`. The campaign digest is `sha256` over the canonical JSON
of `{manifest, plan}`, including hashes of instructions, selected skill files, and
explicit local setup/reset/verifier command files. Transitive fixture dependencies
and remote state still require separately pinned source revisions; the runner does
not recursively discover Python imports or SQL includes. Thus `run` refuses a campaign dir whose stored digest
differs (frozen manifest), so edits require a new `campaign_id` or archiving
the old dir.

## 3. Trial flow

1. Pre-flight (per attempt): auth source present, required executables on
   `PATH`, required env names present. Failure = `infrastructure_error` and
   the campaign stops (fail fast, like setup failures).
2. Fresh private dirs under `<run_root>/<campaign_id>/trials/<id>/attempt-NNN/`:
   `agent-dir/` (0700), `workspace/` (agent cwd), `sessions/`, `private/`.
3. `reset` then `setup` argument arrays run as private side processes
   (cwd `private/{reset,setup}-cwd`, sanitized env, timeout, stdout+stderr
   logged). Failure stops the campaign.
4. The agent sees only `workspace/instruction.md`. Verifiers, expected
   outputs, and references stay outside the workspace by construction.
5. pi runs with cwd = workspace, the generated agent dir via
   `PI_CODING_AGENT_DIR`, `--session-dir` into `sessions/` (persistent —
   no `--no-session`), and the arm flags from README §Runner.
6. stdout streams to `private/events.jsonl` (also parsed live for usage,
   `stopReason`, `agent_settled`); stderr goes to `private/pi-stderr.log`.
   A watchdog enforces `deadline_s` even if pi hangs silently.
7. `verify` runs as a private side process against the artifacts
   (`{artifacts}` = workspace-relative `artifacts` path). Exit codes follow
   `testbed/common/verify_lib.py`: 0 pass, 1 incorrect, 2 incomplete,
   3 missing, 4/other verifier_error.

Statuses: `pending running pass incorrect incomplete missing verifier_error
timeout provider_blocked infrastructure_error aborted`. Every state change
is checkpointed atomically to `campaign.json` plus a per-attempt
`private/trial.json`. Original failures are kept; completed trials are
never overwritten; a trial found `running` on resume is marked `aborted`
("original attempt not replayed") — a fresh attempt happens only as an
explicit new campaign.

## 4. Isolation model — what is proven, what is not

**Config-discovery isolation (implemented + tested).** Fresh agent dir means
no user skills/extensions/settings/prompts/themes bleed; `--no-approve`
ignores all protected project-local resources (`.pi/settings.json`,
`.pi/mcp.json`, `.pi/extensions|.skills|.prompts|.themes`, `.pi/SYSTEM.md`,
ancestor `.agents/skills`); `--no-context-files` stops AGENTS.md/CLAUDE.md
loading (context files load regardless of trust); `--session-dir` overrides
any project `sessionDir` (which pi reads pre-trust). The env handed to pi is
an allowlist: process basics (`PATH`, `HOME`, locale, TLS, proxies) plus
capability `env_names` and manifest `env_pass_names`; provider key/endpoint
variables (`OPENAI_*`, `ANTHROPIC_*`, `ZAI_*`, …) and runner-owned `PI_*`
are scrubbed, and only the scrubbed names (never values) are recorded.

Evidence (`tests/`, offline, real pi 1.0.4 where present):
- `test_isolation.py`: poisoned ancestor `.pi` (mcp.json, settings,
  SYSTEM.md) + `.agents/skills` + AGENTS.md; `pi mcp list` (which reads
  `ProjectTrustStore` itself) discovers the generated catalog and none of
  the poison, for all three arms; `doctor --probe-mcp` end-to-end green.
- `test_configs.py` / `test_e2e_trial.py`: exact argv per arm (recorded by a
  fake pi), identical eager/deferred server definitions except exposure,
  no `ponytail` or non-selected skill anywhere, settings pin explicit
  provider/id, auth symlink/copy modes, 0700 dirs, env scrubbing/allowlist.

**Not proven — do not claim:** same-user file permissions are not a sandbox.
The pi process (and any command it runs) can read files outside the
workspace, including the rig and the auth target of the symlink. Credential
protection is file permissions (0600) plus the fact that auth is never
printed, logged, or embedded. Real sandboxing (container/user isolation) is
a pending privileged-environment validation; until it lands, campaigns
should be marked not-ready for untrusted-content tasks. Instruction-bleed
prevention via `--no-approve`/`--no-context-files` is source-verified but
not observable without a model call.

## 5. Auth reuse

`auth_mode = "symlink"` (default): the trial agent dir's `auth.json` is a
symlink to the private research auth file. Token refreshes by any trial are
shared and persisted (pi locks auth writes), so tokens stay fresh across a
long campaign; the tradeoff is a shared mutable file across concurrent
trials. `auth_mode = "copy"` gives each trial a private snapshot (0600);
refreshes then diverge and are lost per trial, and an expired OAuth token
would need re-copying. Static API-key credentials do not need OAuth refresh.
Subscription-route support and provider reset signals must be verified separately.

## 6. Provider-quota semantics

Only structured provider error fields classify a failure:
`stopReason=error` with `errorMessage`/`rawStopReason`/`diagnostics`
matching quota/rate markers (429, rate limit, quota, billing, …) →
`provider_blocked`; other errors → `infrastructure_error`. Generated task
text is never inspected. On a blocked trial the runner registers capped
exponential backoff per provider: waits `min(base·multiplier^(n-1), cap_s)`
between future trials; if the wait exceeds `pause_above_s` it pauses the
campaign (exit 3) with `blocked_until` checkpointed — `run --resume`
recovers after it, or immediately if an explicitly configured `probe_command`
checks the relevant model provider and exits 0. GitHub API quota is NOT a probe
for OpenAI or Z.ai subscription availability. Probes run as auxiliary checks;
model-backed probe accounting must be implemented before using them in collection.
Every original trial is attempted once (`max_attempts_per_trial` must equal 1).
A blocked trial stays `provider_blocked`; only pending trials continue after waiting.
No task is replayed to replace a primary failure. Backoff counters reset after
non-blocked completion. Generic provider errors stop for investigation.

This is configured backoff, not verified provider-reset parsing: structured reset
timestamps/Retry-After handling and long-lived subscription recovery need live
provider validation. Do not claim automatic reset detection from these tests.

Budgets: `[budget].max_total_tokens` is currently a PER-TRIAL token watchdog
using assistant-message `usage.totalTokens` sums, not a campaign spending cap.
It does not capture auxiliary cache-warming/compaction usage fully. Full-request
capture and complete-run accounting remain collection blockers. Catalog cost
figures from Pi are estimates, not verified subscription bills.

## 7. Model catalog and reproducibility

Model availability is credential-gated (`getAuthenticatedProviders`), so the
auth symlink is also what makes `openai/gpt-6-luna` resolvable inside a
fresh agent dir; `zai/glm-5.3-flash` is in the bundled catalog. `PI_OFFLINE=1`
(default via `[harness.env]`) disables catalog auto-refresh and network
startup work; `PI_SKIP_VERSION_CHECK=1` is always set. Neither changes
retry, cache warming, or compaction behavior — those stay at pi defaults.

## 8. Before a live run

Use a new, private manifest for each environment and record the exact Pi build,
provider/model identifiers, settings, capability versions, and task-data
revisions. Confirm that every referenced task and verifier exists, every
credential is intentionally scoped, and each setup/reset command targets only
throwaway resources. Check container and browser sandbox behavior in the target
environment; do not infer isolation from configuration alone.

Begin with offline tests, then static manifest validation and planning. Only
continue to network probes or model calls when explicitly intended. Preserve
original failures and run outputs privately; never replace unsuccessful trials
with unrecorded retries or publish raw prompts, responses, credentials, or
provider payloads by default.
