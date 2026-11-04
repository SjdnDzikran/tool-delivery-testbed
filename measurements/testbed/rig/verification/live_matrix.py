#!/usr/bin/env python3
"""Generate verification manifests and run bounded live suites [ours].

Suites (each is one runner campaign; every trial spends model tokens):
  probe       eager x glm53flash x required          (1 trial)  observer
  required    eager/deferred/cli x glm/gpt x required (6 trials) observer
  full-glm    eager/deferred/cli x glm53flash x full  (3 trials) observer
  plain       eager x glm53flash, unobserved binary   (1 trial)  faithfulness
  controls    eager x glm53flash, the two rig controls(2 trials) observer
  poisoned    eager/deferred/cli x glm53flash, ancestor
              poison fixture around the run root      (3 trials) observer

Private data (raw payloads, sessions, events) stays under --tmp-root
(default /tmp). Nothing here mutates the repo or the runner.

Usage:
  python3 live_matrix.py emit SUITE --tmp-root DIR     # write manifest
  python3 live_matrix.py run   SUITE --tmp-root DIR    # emit + runner run
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RIG = HERE.parent
RUNNER = RIG / "runner.py"
REPO = HERE.parents[3]
CONTROLS = REPO / "measurements" / "testbed" / "controls"
CANARY = HERE / "canary"
OBSERVER_WRAPPER = HERE / "observer" / "observed-pi-research.sh"
PLAIN_HARNESS = Path.home() / ".local" / "bin" / "pi-research"
AUTH = Path.home() / ".pi" / "research" / "agent" / "auth.json"

POISON_MARKERS = {
    "mcp": "POISON-MCP-MARKER",
    "skill": "POISON-SKILL-MARKER",
    "system": "POISON-SYSTEM-MARKER",
    "agents": "POISON-AGENTS-MARKER",
    "claude": "POISON-CLAUDE-MARKER",
    "ext": "POISON-EXT-MARKER",
    "prompt": "POISON-PROMPT-MARKER",
    "theme": "POISON-THEME-MARKER",
    "ponytail": "POISON-PONYTAIL-MARKER",
}

MODELS = {
    "glm53flash": {"provider": "zai", "id": "glm-5.3-flash", "thinking": "max"},
    "gpt6luna": {"provider": "openai", "id": "gpt-6-luna", "thinking": "max"},
}


def tomlify_str(v: str) -> str:
    return json.dumps(v)


def build_poison(root: Path) -> Path:
    """Ancestor poison fixture around the run root (project-level bleed)."""
    p = root / "poisoned-project"
    (p / ".pi" / "extensions").mkdir(parents=True, exist_ok=True)
    (p / ".pi" / "skills" / "poison-skill").mkdir(parents=True, exist_ok=True)
    (p / ".pi" / "prompts").mkdir(parents=True, exist_ok=True)
    (p / ".pi" / "themes").mkdir(parents=True, exist_ok=True)
    (p / ".agents" / "skills" / "ponytail").mkdir(parents=True, exist_ok=True)
    (p / ".pi" / "mcp.json").write_text(json.dumps({
        "mcpServers": {"poison-mcp": {
            "command": "python3", "args": ["-c", "print('x')"],
            "exposure": "direct",
            "description": POISON_MARKERS["mcp"] + " server"}}}))
    (p / ".pi" / "settings.json").write_text(json.dumps({
        "defaultProvider": "zai", "defaultModel": "poison-model",
        "sessionDir": str(p / "poison-sessions")}))
    (p / ".pi" / "SYSTEM.md").write_text(POISON_MARKERS["system"] + "\n")
    (p / ".pi" / "extensions" / "poison-ext.ts").write_text(
        "export default function (pi) {\n"
        f"  pi.registerTool({{name: 'poison_tool', description: '{POISON_MARKERS['ext']}',"
        " parameters: {type: 'object', properties: {}},\n"
        "    execute: async () => ({content: [{type: 'text', text: 'poison'}],"
        " details: undefined})});\n}\n")
    (p / ".pi" / "skills" / "poison-skill" / "SKILL.md").write_text(
        "---\nname: poison-skill\ndescription: " + POISON_MARKERS["skill"] +
        "\n---\n\nPoison body.\n")
    (p / ".pi" / "prompts" / "poison-prompt.md").write_text(
        POISON_MARKERS["prompt"] + "\n")
    (p / ".pi" / "themes" / "poison-theme.json").write_text(
        json.dumps({"name": POISON_MARKERS["theme"]}) + "\n")
    (p / ".agents" / "skills" / "ponytail" / "SKILL.md").write_text(
        "---\nname: ponytail\ndescription: " + POISON_MARKERS["ponytail"] +
        "\n---\n\nPoison ponytail decoy.\n")
    (p / "AGENTS.md").write_text(POISON_MARKERS["agents"] + "\n")
    (p / "CLAUDE.md").write_text(POISON_MARKERS["claude"] + "\n")
    return p


def emit_manifest(suite: str, tmp_root: Path) -> tuple[Path, dict]:
    (tmp_root / "manifests").mkdir(parents=True, exist_ok=True)
    observer_base = tmp_root / "observer"
    raw_base = tmp_root / "raw"
    meta: dict = {"suite": suite, "trials_expected": None}

    if suite == "probe":
        modes, models, catalogs = ["eager"], ["glm53flash"], ["required"]
        binary, campaign = str(OBSERVER_WRAPPER), "verify-probe"
    elif suite == "required":
        modes, models, catalogs = ["eager", "deferred", "cli"], \
            ["glm53flash", "gpt6luna"], ["required"]
        binary, campaign = str(OBSERVER_WRAPPER), "verify-required"
    elif suite == "full-glm":
        modes, models, catalogs = ["eager", "deferred", "cli"], \
            ["glm53flash"], ["full"]
        binary, campaign = str(OBSERVER_WRAPPER), "verify-full-glm"
    elif suite == "plain":
        modes, models, catalogs = ["eager"], ["glm53flash"], ["required"]
        binary, campaign = str(PLAIN_HARNESS), "verify-plain-eager-glm"
        meta["unobserved"] = True
    elif suite == "controls":
        modes, models, catalogs = ["eager"], ["glm53flash"], ["required"]
        binary, campaign = str(OBSERVER_WRAPPER), "verify-controls"
    elif suite == "poisoned":
        modes, models, catalogs = ["eager", "deferred", "cli"], \
            ["glm53flash"], ["required"]
        binary, campaign = str(OBSERVER_WRAPPER), "verify-poisoned"
        meta["poisoned_run_root"] = True
    else:
        raise SystemExit(f"unknown suite {suite}")

    run_root = tmp_root / "runs"
    if meta.get("poisoned_run_root"):
        poison_dir = build_poison(tmp_root)
        run_root = poison_dir / "runs"
        meta["poison_dir"] = str(poison_dir)

    task_entries = []
    if suite == "controls":
        task_entries.append(([
            "[tasks.control_1]",
            f"instruction = {tomlify_str(str(CONTROLS / 'control_1_filter_sort' / 'instruction.md'))}",
            "capabilities = []", "catalog = []", "deadline_s = 600",
            "verify = [" + ", ".join(tomlify_str(x) for x in [
                "python3", str(CONTROLS / "control_1_filter_sort" / "verify.py"),
                "--artifacts", "{workspace}"]) + "]",
        ]))
        task_entries.append(([
            "[tasks.control_2]",
            f"instruction = {tomlify_str(str(CONTROLS / 'control_2_group_aggregate' / 'instruction.md'))}",
            "capabilities = []", "catalog = []", "deadline_s = 600",
            "verify = [" + ", ".join(tomlify_str(x) for x in [
                "python3", str(CONTROLS / "control_2_group_aggregate" / "verify.py"),
                "--artifacts", "{workspace}"]) + "]",
        ]))
    else:
        task_entries.append([
            "[tasks.canary_echo]",
            "instruction = " + tomlify_str(
                str(CANARY / "tasks" / "canary-echo" / "instruction.md")),
            'capabilities = ["canary"]',
            'catalog = ["canary"]',
            "deadline_s = 420",
            "verify = [" + ", ".join(tomlify_str(x) for x in [
                "python3", str(HERE / "verify_canary.py"),
                "--artifacts", "{workspace}"]) + "]",
        ])

    lines = [
        "# Generated by rig/verification/live_matrix.py — do not hand-edit.",
        "schema_version = 1",
        "env_pass_names = [" + ", ".join(tomlify_str(x) for x in
                                         ["PI_OBSERVER_DIR",
                                          "PI_OBSERVER_RAW_DIR"]) + "]",
        "[harness]",
        f"campaign_id = {tomlify_str(campaign)}",
        f"binary = {tomlify_str(binary)}",
        'required_version = "1.0.4"',
        f"auth_source = {tomlify_str(str(AUTH))}",
        'auth_mode = "symlink"',
        "",
        "[harness.env]",
        'PI_OFFLINE = "1"',
        "",
        "[models.glm53flash]",
        f"provider = {tomlify_str(MODELS['glm53flash']['provider'])}",
        f"id = {tomlify_str(MODELS['glm53flash']['id'])}",
        f"thinking = {tomlify_str(MODELS['glm53flash']['thinking'])}",
        "",
        "[models.gpt6luna]",
        f"provider = {tomlify_str(MODELS['gpt6luna']['provider'])}",
        f"id = {tomlify_str(MODELS['gpt6luna']['id'])}",
        f"thinking = {tomlify_str(MODELS['gpt6luna']['thinking'])}",
        "",
        "[catalog.canary]",
        'command = "python3"',
        "args = [" + ", ".join(tomlify_str(x) for x in
                               [str(CANARY / "mcp-canary-server.py"),
                                "--server", "canary"]) + "]",
        "description = " + tomlify_str(
            "Verification canary: canary_echo echoes text with the "
            "CANARY_ECHO_OK prefix."),
        "timeout = 30",
        "",
        "[catalog.decoy]",
        'command = "python3"',
        "args = [" + ", ".join(tomlify_str(x) for x in
                               [str(CANARY / "mcp-canary-server.py"),
                                "--server", "decoy"]) + "]",
        "description = " + tomlify_str(
            "Verification decoy: DECOY-ONLY server that must appear only in "
            "full-catalog trials."),
        "timeout = 30",
        "",
        "[capabilities.canary]",
        'kind = "cli"',
        'skills = ["canary-skill"]',
        'executables = ["canary-cli"]',
        "",
        "[capabilities.decoy-cap]",
        'kind = "cli"',
        'skills = ["decoy-skill"]',
        'executables = ["canary-cli"]',
        "",
        "[paths]",
        f"skills_dir = {tomlify_str(str(CANARY / 'skills'))}",
        f"run_root = {tomlify_str(str(run_root))}",
        *[ln for entry in task_entries for ln in [*entry, ""]],
        "[matrix]",
        f"modes = [{', '.join(tomlify_str(m) for m in modes)}]",
        f"models = [{', '.join(tomlify_str(m) for m in models)}]",
        f"catalogs = [{', '.join(tomlify_str(c) for c in catalogs)}]",
        "reps = 1",
        "seed = 2026",
        "",
        "[quota]",
        "base_s = 20", "multiplier = 2", "cap_s = 60", "pause_above_s = 30",
        "max_attempts_per_trial = 1",
        "",
        "[budget]",
        "max_total_tokens = 300000",
        "",
    ]
    n_tasks = 2 if suite == "controls" else 1
    meta["trials_expected"] = len(modes) * len(models) * n_tasks
    meta["campaign_id"] = campaign
    meta["binary"] = binary
    meta["run_root"] = str(run_root)
    meta["observer_base"] = str(observer_base)
    meta["raw_base"] = str(raw_base)
    path = tmp_root / "manifests" / f"{suite}.toml"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path, meta


def run_suite(suite: str, tmp_root: Path, timeout: int) -> int:
    path, meta = emit_manifest(suite, tmp_root)
    env = dict(os.environ)
    env["PATH"] = str(CANARY) + os.pathsep + env.get("PATH", "")
    expected = meta["trials_expected"]
    env["PI_OBSERVER_DIR"] = meta["observer_base"] + "/" + meta["campaign_id"]
    env["PI_OBSERVER_RAW_DIR"] = meta["raw_base"] + "/" + meta["campaign_id"]
    deadline_cap = 600
    budget = expected * deadline_cap + 300
    if timeout:
        budget = timeout
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "run", str(path)],
        env=env, capture_output=True, text=True, timeout=budget)
    (tmp_root / "suite-logs").mkdir(exist_ok=True)
    (tmp_root / "suite-logs" / f"{suite}.stdout.log").write_text(proc.stdout)
    (tmp_root / "suite-logs" / f"{suite}.stderr.log").write_text(proc.stderr)
    print(f"[{suite}] runner rc={proc.returncode} (expected {expected} trials)")
    print(proc.stdout[-3000:])
    if proc.returncode not in (0, 3):
        print(proc.stderr[-2000:], file=sys.stderr)
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("emit", "run"):
        p = sub.add_parser(name)
        p.add_argument("suite")
        p.add_argument("--tmp-root", required=True, type=Path)
        p.add_argument("--timeout", type=int, default=0)
    args = ap.parse_args()
    args.tmp_root = args.tmp_root.resolve()
    if args.cmd == "emit":
        path, meta = emit_manifest(args.suite, args.tmp_root)
        print(json.dumps({"manifest": str(path), **meta}, indent=2))
        return 0
    return run_suite(args.suite, args.tmp_root, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
