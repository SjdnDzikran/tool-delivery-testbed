# GAIA picks — no-search tool-dependence pretest protocol

**Status: [ours — run 2026-11-06 on the two campaign questions only, after the
campaign, at student direction]. Neither question passed Section 5: 9 of 12 runs
contained the reference answer. See [`results.csv`](results.csv); `reference_in_answer`
catches sentence answers that `answers_equal` does not. The questions stay in the
dataset and the failure is reported in the thesis.**

## 1. Purpose

The GAIA-derived tasks measure **delivery overhead** (how search capability is
delivered: eager Brave Search MCP vs deferred MCP via tool search vs `bx`
CLI+skills), not model intelligence. A task only qualifies if it **cannot**
be answered from the models' parametric knowledge alone. This pretest
establishes tool dependence before any campaign run.

## 2. Rig and configuration

- Run on the **experimenters' separate Pi 1.0.4 rig** — not the campaign
  harness — so the pretest cannot contaminate campaign state. Pi version must
  be pinned and recorded (the campaign pins 1.0.4).
- Both campaign models, separately and with their fixed API-key provider and
  settings per the design: **GPT-6 Luna** and **GLM 5.3 Flash**. Record the
  exact API identifiers, providers, and settings in the run log before the
  first run.
- Search capability absent for every pretest run:
  - no MCP servers (launch Pi with MCP disabled — the design's `--no-mcp`
    class of flag; confirm the exact accepted flag spelling with `pi --help`
    on the installed 1.0.4 build before the first run and record it);
  - no skills loaded (`--no-skills` class of flag; same verification note);
  - `bx` (Brave Search CLI) not reachable: run from a shell whose `PATH`
    excludes the skill/CLI shims (verify with `command -v bx` failing);
  - JSON output mode (`--mode json` class of flag) so answers are extracted
    mechanically.
  These flag descriptions follow the experiment design; **verify exact flag
  behavior against the installed Pi 1.0.4 — do not assume**.
- Smoke check per model before the battery: one probe run confirming the
  session exposes no search tools and no `bx` on PATH.

## 3. Candidates and run matrix

- Candidates: all 10 entries of [`../candidates.json`](../candidates.json)
  (shortlist order = rank order).
- Per candidate: **both models × 3 repetitions = 6 runs**; 10 candidates →
  **60 runs** total. Repetitions are independent sessions (fresh process, no
  shared context, fixed settings).
- Prompt: the task `question` field verbatim, nothing else. No hints that
  search is unavailable.
- Capture the raw final answer from the JSON session output.

## 4. Scoring

Score each run with the same answer-equality logic the campaign verifier
uses: `answers_equal(reference, raw_answer)` from
[`../../common/verify_lib.py`](../../common/verify_lib.py) (exact, normalized,
or numeric equality) — i.e. the "answers_equal logic" of
[`../verify_gaia.py`](../verify_gaia.py), without the source/evidence checks,
which are meaningless without search.

Record one row per run in [`results.csv`](results.csv):
`task_id, model, rep, raw_answer, tool_dependent_pass`
(`tool_dependent_pass` = 1 if the answer matched the reference **without**
search — a leak; 0 if it did not).

## 5. Qualification rule (tool dependence)

A candidate **qualifies only if both models fail all repetitions** — 0/6
matching answers. Any single matching answer shows the fact (or an
acceptable paraphrase) is retrievable from weights; drop the candidate.
Rank survivors by their shortlist rank.

## 6. Route-sufficiency check

For each qualifying candidate, each delivery route must complete the question
**once** with logged, manually inspected evidence (assisted runs are
acceptable; log date, rig, route, command line, and artifact path):

1. eager MCP — Brave Search MCP server loaded up front;
2. deferred MCP — same server deferred behind Pi's native tool search, the
   model discovering it mid-task;
3. CLI — `bx` via the progressively disclosed search skill.

A route run counts only if the final answer matches the reference and at
least one cited URL/quote is present in the session artifacts. A candidate
that any route cannot complete is dropped (route inequivalence would confound
the comparison).

## 7. Decision rules (ordered)

1. Discard any candidate with a no-search leak (Section 5).
2. Discard any remaining candidate failing route-sufficiency (Section 6).
3. Order survivors by shortlist rank (Section 5).
4. Take the top 2 as the proposed GAIA tasks; update
   [`../gaia_tasks/`](../gaia_tasks/) if it differs from the current picks.
5. Log the pretest session in `docs/ai-usage-log.md` per project rules.
6. **student approves final 2**
