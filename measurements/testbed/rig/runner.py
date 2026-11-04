#!/usr/bin/env python3
"""Manifest-driven campaign runner for the Pi-only tool-delivery study [ours].

Single stdlib entry point (Python 3.11+, tomllib). Subcommands:

    validate MANIFEST        static manifest checks + readiness report
    plan    MANIFEST [--write PATH]
    run     MANIFEST [--resume]
    resume  MANIFEST         alias of run --resume
    status  MANIFEST
    doctor  MANIFEST [--probe-mcp]
    trial   ...              single ad-hoc trial (smoke; --help for flags)

Design notes are in rig/GUIDE.md. The runner isolates configuration
discovery (fresh private agent dir, explicit flags); it does NOT provide an
OS security boundary — same-user processes can read files outside the
workspace. Credentials stay private: auth.json is referenced, never printed,
logged, or embedded.

Route compliance is audited separately from captured transcripts; a passing
verifier alone is not full research success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

SCHEMA_VERSION = 1
MODES = ("eager", "deferred", "cli")
STATUSES = (
    "pending", "running", "pass", "incorrect", "incomplete", "missing",
    "verifier_error", "timeout", "provider_blocked", "infrastructure_error",
    "aborted",
)
TERMINAL = {"pass", "incorrect", "incomplete", "missing", "verifier_error",
            "timeout", "provider_blocked", "infrastructure_error", "aborted"}
# Env vars never passed to trials unless explicitly allowlisted in the
# manifest: provider auth/endpoint overrides and Pi process overrides the
# runner owns. Values are never recorded — only the scrubbed names.
SCRUB_ENV_RE = re.compile(
    r"^(?:OPENAI|ANTHROPIC|ZAI|ZHIPU|GOOGLE|GEMINI|GROQ|MISTRAL|DEEPSEEK|XAI|"
    r"COHERE|OPENROUTER|AZURE|MOONSHOT|DASHSCOPE|FIREWORKS|TOGETHER|"
    r"PERPLEXITY|AI21|HF|HUGGINGFACE)[A-Z0-9_]*$",
    re.IGNORECASE,
)
SCRUB_ENV_EXACT = {"PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR",
                   "PI_OFFLINE", "PI_SKIP_VERSION_CHECK", "PI_PACKAGE_DIR"}
QUOTA_MARKERS = ("429", "rate limit", "ratelimit", "rate_limit", "quota",
                 "insufficient_quota", "billing", "usage limit", "credit",
                 "exceeded your current")
# Base env always passed to trials: process basics, locale, TLS, proxies.
# Everything else must be explicitly allowlisted (capability env_names or
# manifest env_pass_names) so stray credentials never reach the agent env.
BASE_ENV_KEEP = {"PATH", "HOME", "SHELL", "USER", "LOGNAME", "LANG",
                 "TERM", "TMPDIR", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR",
                 "SSH_AUTH_SOCK", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy",
                 "https_proxy", "NO_PROXY", "no_proxy", "ALL_PROXY",
                 "all_proxy", "XDG_RUNTIME_DIR"}
DEFAULT_RUN_ROOT = Path.home() / ".pi-research-runs"
DEFAULT_QUOTA = {"base_s": 60, "multiplier": 2, "cap_s": 1800,
                 "pause_above_s": 600, "max_attempts_per_trial": 1,
                 "probe_timeout_s": 30, "probe_command": None}
ARM_EXTENSIONS = {
    "eager": ["builtin:mcp"],
    "deferred": ["builtin:mcp", "builtin:tool-search"],
    # cli arm: no -e at all; --no-mcp plus explicit --skill flags.
    "cli": [],
}


class ManifestError(Exception):
    pass


def manifest_dir_of(m: dict) -> str:
    return m["paths"]["_manifest_dir"]


class StopCampaign(Exception):
    """Setup or pre-flight failure: stop the whole campaign."""


# ---------------------------------------------------------------- utilities

def sha256_json(obj) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def atomic_append_jsonl(path: Path, obj) -> None:
    """Append one record with a single write; readers see whole lines."""
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


def now_utc() -> float:
    return time.time()


def zulu(t: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None


def run_cmd(argv: list[str], cwd: Path, env: dict, timeout: int,
            out_dir: Path, tag: str) -> tuple[int, str]:
    """Run one argument-array command as a private side subprocess."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cwd.mkdir(parents=True, exist_ok=True)
    log = out_dir / f"{tag}.log"
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace",
        )
        log.write_text(proc.stdout or "", encoding="utf-8")
        return proc.returncode, proc.stdout or ""
    except subprocess.TimeoutExpired as exc:
        text = f"TIMEOUT after {timeout}s\n{exc.stdout or ''}"
        log.write_text(text, encoding="utf-8")
        return 124, text
    except OSError as exc:
        text = f"OSERROR {exc}"
        log.write_text(text, encoding="utf-8")
        return 127, text


def substitute(arg: str, places: dict[str, str]) -> str:
    for key, val in places.items():
        arg = arg.replace("{" + key + "}", val)
    return arg


def sanitized_env() -> dict[str, str]:
    """Host env minus runner-owned/scrubbed keys (for probes)."""
    return {k: v for k, v in os.environ.items()
            if k not in SCRUB_ENV_EXACT and not SCRUB_ENV_RE.match(k)}


# ---------------------------------------------------------------- manifest

def load_manifest(path: Path) -> dict:
    raw = path.read_bytes()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"TOML parse error: {exc}") from exc
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ManifestError(
            f"schema_version must be {SCHEMA_VERSION}, got "
            f"{data.get('schema_version')!r}")
    if b"PIN_VERSION" in raw:
        raise ManifestError(
            "manifest contains unresolved PIN_VERSION placeholder")
    m = normalize_manifest(path.resolve(), data)
    m["paths"]["_manifest_dir"] = str(path.resolve().parent)
    return m


def normalize_manifest(manifest_path: Path, data: dict) -> dict:
    """Resolve relative paths against the manifest dir; fill defaults.

    The returned dict is the frozen manifest: it feeds the campaign digest,
    so it must contain everything the run depends on.
    """
    base = manifest_path.parent
    m = json.loads(json.dumps(data))  # deep copy of parsed TOML

    def r(p: str) -> str:
        q = Path(p).expanduser()
        return str(q if q.is_absolute() else (base / q).resolve())

    h = m.setdefault("harness", {})
    for key in ("binary", "auth_source", "gaia_verification_receipt"):
        if key in h:
            h[key] = r(h[key])
    h.setdefault("required_version", None)
    h.setdefault("auth_mode", "symlink")
    h.setdefault("env", {})
    paths = m.setdefault("paths", {})
    paths["skills_dir"] = r(paths.get("skills_dir", str(base / "skills")))
    paths["run_root"] = r(paths.get("run_root", str(DEFAULT_RUN_ROOT)))
    m.setdefault("env", {})
    m.setdefault("env_pass_names", [])
    m["quota"] = {**DEFAULT_QUOTA, **m.get("quota", {})}
    m.setdefault("budget", {})
    mat = m.setdefault("matrix", {})
    mat.setdefault("modes", list(MODES))
    mat.setdefault("models", [])
    mat.setdefault("catalogs", ["required"])
    mat.setdefault("reps", 1)
    mat.setdefault("seed", 0)
    for t_id, task in m.setdefault("tasks", {}).items():
        task["instruction"] = r(task["instruction"])
        if "assets" in task:
            task["assets"] = {role: r(p) for role, p in task["assets"].items()}
        task.setdefault("capabilities", [])
        task.setdefault("catalog", [])  # [] means: MCP-native control (no servers)
        task.setdefault("artifacts", ".")
        task.setdefault("setup", None)
        task.setdefault("reset", None)
        task.setdefault("verify_timeout_s", 120)
        task.setdefault("setup_timeout_s", 300)
    # Freeze public local inputs, not credentials or mutable provider tokens.
    assets = {Path(t["instruction"]) for t in m["tasks"].values()}
    if h.get('gaia_verification_receipt'):
        assets.add(Path(h['gaia_verification_receipt']))
    assets.update(Path(p) for task in m["tasks"].values() for p in task.get("assets", {}).values())
    for cap in m.get("capabilities", {}).values():
        for skill in cap.get("skills", []):
            root = Path(paths["skills_dir"]) / skill
            if root.is_dir():
                assets.update(p for p in root.rglob("*") if p.is_file())
    for task in m["tasks"].values():
        for command in (task.get("verify"), task.get("reset"), task.get("setup")):
            for argument in command or []:
                candidate = argument.replace("{manifest_dir}", str(base)).replace(
                    "{rig_dir}", str(Path(__file__).resolve().parent))
                if Path(candidate).is_absolute() and Path(candidate).is_file():
                    assets.add(Path(candidate))
    m["asset_hashes"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(assets) if p.is_file()}
    return m


def validate_manifest(m: dict) -> list[str]:
    """Static checks; returns a list of error strings (empty = valid)."""
    errors: list[str] = []

    def need(cond, msg):
        if not cond:
            errors.append(msg)

    h = m["harness"]
    need(h.get("binary"), "[harness] binary is required")
    need(h.get("auth_source"), "[harness] auth_source is required")
    need(h.get("auth_mode") in ("symlink", "copy"),
         "[harness] auth_mode must be symlink or copy")
    need(not h.get("required_version") or isinstance(h["required_version"], str),
         "[harness] required_version must be a string like \"1.0.4\"")
    for key, val in h.get("env", {}).items():
        need(isinstance(val, str), f"[harness.env] {key} must be a string")

    for m_id, model in m.get("models", {}).items():
        need(isinstance(model, dict), f"[models.{m_id}] must be a table")
        for key in ("provider", "id"):
            need(model.get(key), f"[models.{m_id}] {key} is required "
                 "(explicit provider and model id, no defaults)")
        th = model.get("thinking", "medium")
        need(th in ("off", "minimal", "low", "medium", "high", "xhigh", "max"),
             f"[models.{m_id}] thinking {th!r} invalid")

    for c_id, cap in m.get("capabilities", {}).items():
        need(cap.get("kind") == "cli", f"[capabilities.{c_id}] kind must be cli")
        need(cap.get("skills"), f"[capabilities.{c_id}] skills list is required")
        need(cap.get("executables"),
             f"[capabilities.{c_id}] executables list is required")

    for s_id, srv in m.get("catalog", {}).items():
        need(srv.get("kind") in (None, "mcp"),
             f"[catalog.{s_id}] kind must be mcp")
        need(bool(srv.get("command")) ^ bool(srv.get("url")),
             f"[catalog.{s_id}] exactly one of command or url is required")
        need("exposure" not in srv,
             f"[catalog.{s_id}] exposure is owned by the mode, not the manifest")
        for k in ("args",):
            if k in srv:
                need(isinstance(srv[k], list) and all(isinstance(a, str) for a in srv[k]),
                     f"[catalog.{s_id}] args must be an array of strings")
        if "env" in srv:
            need(isinstance(srv["env"], dict), f"[catalog.{s_id}] env must be a table")

    need(bool(m.get("tasks")), "at least one [tasks.*] definition is required")
    cid = h.get("campaign_id")
    need(bool(cid) and re.fullmatch(r"[A-Za-z0-9._-]+", str(cid)),
         "[harness] campaign_id is required (letters, digits, ., _, -)")
    catalog_ids = set(m.get("catalog", {}))
    cap_ids = set(m.get("capabilities", {}))
    for t_id, task in m["tasks"].items():
        if not Path(task["instruction"]).is_file():
            errors.append(f"[tasks.{t_id}] instruction not found: "
                          f"{task['instruction']}")
        need(task.get("deadline_s"), f"[tasks.{t_id}] deadline_s is required "
             "(fixed per task across arms)")
        for c in task["capabilities"]:
            need(c in cap_ids, f"[tasks.{t_id}] unknown capability {c!r}")
        for c in (task["catalog"] if isinstance(task["catalog"], list) else []):
            need(c in catalog_ids, f"[tasks.{t_id}] unknown catalog entry {c!r}")
        for key in ("setup", "reset", "verify"):
            cmd = task.get(key)
            if cmd is not None:
                need(isinstance(cmd, list) and cmd and
                     all(isinstance(a, str) for a in cmd),
                     f"[tasks.{t_id}] {key} must be a non-empty argument array")
        need(task.get("verify"), f"[tasks.{t_id}] verify array is required")

    mat = m["matrix"]
    for mode in mat["modes"]:
        need(mode in MODES, f"[matrix] unknown mode {mode!r}")
    need(bool(mat["models"]), "[matrix] models is required")
    for m_id in mat["models"]:
        need(m_id in m.get("models", {}), f"[matrix] unknown model {m_id!r}")
    for c in mat["catalogs"]:
        need(c in ("full", "required"),
             f"[matrix] catalog variant {c!r} must be full or required")
    need(isinstance(mat["reps"], int) and mat["reps"] >= 1,
         "[matrix] reps must be a positive integer")
    need(isinstance(mat["seed"], int), "[matrix] seed must be an integer")

    q = m["quota"]
    need(q["base_s"] > 0 and q["cap_s"] >= q["base_s"]
         and q["pause_above_s"] >= 0 and q["max_attempts_per_trial"] == 1,
         "[quota] policy values out of range")
    if m["budget"]:
        need(m["budget"].get("max_total_tokens"),
             "[budget] max_total_tokens is required when [budget] is set")
    skills_dir = Path(m["paths"]["skills_dir"])
    for c_id, cap in m.get("capabilities", {}).items():
        for s in cap["skills"]:
            if not (skills_dir / s / "SKILL.md").is_file():
                errors.append(f"[capabilities.{c_id}] skill {s!r} has no "
                              f"SKILL.md under {skills_dir}")
    return errors


# ---------------------------------------------------------------- plan

def build_plan(m: dict) -> list[dict]:
    """Deterministic trial order: seeded shuffle over the full matrix.

    Axes: (task, catalog variant, mode, model, rep). The catalog variant
    axis applies to the MCP modes only; the cli arm always uses the task's
    own capability list, so it is expanded once with variant "n/a".
    """
    entries: list[tuple] = []
    for t_id in sorted(m["tasks"]):
        task = m["tasks"][t_id]
        # A task with no required servers is an MCP-native control: it runs
        # once, not once per catalog variant.
        for variant in m["matrix"]["catalogs"]:
            for mode in m["matrix"]["modes"]:
                entries.append((t_id, variant, mode))
    plan = []
    for t_id, variant, mode in entries:
        for model in sorted(m["matrix"]["models"]):
            for rep in range(1, m["matrix"]["reps"] + 1):
                plan.append({"task": t_id, "catalog": variant, "mode": mode,
                             "model": model, "rep": rep})
    random.Random(f"pi-study:{m['matrix']['seed']}").shuffle(plan)
    for i, spec in enumerate(plan, 1):
        spec["trial_id"] = f"t{i:04d}"
    return plan


def select_catalog(m: dict, spec: dict) -> list[str]:
    """MCP server names enabled for a trial."""
    task = m["tasks"][spec["task"]]
    if spec["mode"] == "cli":
        return []
    if spec["catalog"] == "required":
        return sorted(task["catalog"])
    return sorted(m.get("catalog", {}))


def select_capabilities(m: dict, spec: dict) -> list[str]:
    """CLI capability catalog, varied on the same axis as MCP catalogs."""
    if spec["mode"] != "cli":
        return []
    if spec["catalog"] == "full":
        return sorted(m["capabilities"])
    return sorted(m["tasks"][spec["task"]]["capabilities"])


def select_skills(m: dict, spec: dict) -> list[str]:
    """Rig skills copied into the trial agent dir (cli arm only).

    MCP arms run with --no-skills and carry no skills at all, so the
    delivery route is the only difference between arms.
    """
    if spec["mode"] != "cli":
        return []
    skills: list[str] = []
    for c in select_capabilities(m, spec):
        skills.extend(m["capabilities"][c]["skills"])
    return sorted(set(skills))


# ---------------------------------------------------------------- campaign

class Campaign:
    def __init__(self, manifest_path: Path, manifest_dict: dict | None = None):
        self.manifest_path = manifest_path
        self.m = manifest_dict if manifest_dict is not None \
            else load_manifest(manifest_path)
        errors = validate_manifest(self.m)
        if errors:
            raise ManifestError("invalid manifest:\n  - " +
                                "\n  - ".join(errors))
        self.plan = build_plan(self.m)
        self.digest = sha256_json({"manifest": self.m, "plan": self.plan})
        self.dir = Path(self.m["paths"]["run_root"]) / self.m["harness"]["campaign_id"]
        self.state_path = self.dir / "campaign.json"

    # -- state --
    def load_or_init(self) -> dict:
        if self.state_path.is_file():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if state["digest"] != self.digest:
                raise ManifestError(
                    f"campaign {self.dir} holds digest {state['digest'][:19]}… "
                    "but the manifest/plan now hashes to "
                    f"{self.digest[:19]}…; the frozen manifest changed. "
                    "Archive the campaign dir or change campaign_id.")
            return state
        state = {
            "schema": "campaign-v1", "campaign_id": self.m["harness"]["campaign_id"],
            "digest": self.digest, "created_utc": zulu(now_utc()),
            "manifest": self.m, "plan": self.plan,
            "trials": {s["trial_id"]: self._fresh_trial(s) for s in self.plan},
            "provider_backoff": {}, "events": [],
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "trials").mkdir(mode=0o700, exist_ok=True)
        atomic_write_json(self.state_path, state)
        return state

    def save(self, state: dict) -> None:
        atomic_write_json(self.state_path, state)

    def _fresh_trial(self, spec: dict) -> dict:
        return {"spec": spec, "status": "pending", "attempts": 0,
                "blocked_until": None, "last_error": None, "exit_code": None,
                "pi_exit_code": None, "stop_reason": None, "usage_total_tokens": 0,
                "verifier_exit_code": None, "started_utc": None,
                "ended_utc": None, "argv_flags": None, "prompt_sha256": None,
                "scrubbed_env_names": [], "notes": []}

    def trial_dir(self, trial_id: str) -> Path:
        return self.dir / "trials" / trial_id

    def log(self, msg: str) -> None:
        line = f"[{zulu(now_utc())}] {msg}"
        print(line, flush=True)
        with open(self.dir / "campaign.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


# ---------------------------------------------------------------- env

def build_trial_env(m: dict, enabled_env_names: list[str],
                    agent_dir: Path) -> tuple[dict, list[str]]:
    """Sanitized env for the pi process and its capability subprocesses.

    Scrubbed: provider key/endpoint vars and Pi overrides the runner owns.
    Passed: manifest allowlist + env names required by enabled capabilities.
    Scrubbed names (never values) are returned for the audit record.
    """
    env: dict[str, str] = {}
    scrubbed: list[str] = []
    allow = (set(m.get("env_pass_names", [])) | set(enabled_env_names)
             | BASE_ENV_KEEP)
    for key, val in os.environ.items():
        if key in allow or key.startswith("LC_"):
            env[key] = val
        elif key in SCRUB_ENV_EXACT or SCRUB_ENV_RE.match(key):
            scrubbed.append(key)
        # anything else: dropped silently (unknown host env never bleeds)
    for key, val in m["harness"].get("env", {}).items():
        env[key] = val
    env.setdefault("PI_OFFLINE", "1")
    env["PI_SKIP_VERSION_CHECK"] = "1"
    env["PI_CODING_AGENT_DIR"] = str(agent_dir)
    env.pop("PI_CODING_AGENT_SESSION_DIR", None)
    return env, sorted(scrubbed)


# ---------------------------------------------------------------- trial prep

def prepare_agent_dir(m: dict, spec: dict, trial: dict, tdir: Path) -> dict:
    """Fresh private Pi agent dir with ONLY generated settings/mcp/skills."""
    agent_dir = tdir / "agent-dir"
    agent_dir.mkdir(mode=0o700)
    mode = spec["mode"]
    model = m["models"][spec["model"]]

    settings = {
        "defaultProvider": model["provider"],
        "defaultModel": model["id"],
        "defaultThinkingLevel": model.get("thinking", "medium"),
    }
    (agent_dir / "settings.json").write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    servers = select_catalog(m, spec)
    if servers:
        defs = {}
        for name in servers:
            entry = {k: v for k, v in m["catalog"][name].items()
                     if k not in ("kind", "env_names")}
            entry["exposure"] = "direct" if mode == "eager" else "deferred"
            defs[name] = entry
        # eager and deferred share identical definitions except exposure.
        (agent_dir / "mcp.json").write_text(
            json.dumps({"mcpServers": defs}, indent=2) + "\n", encoding="utf-8")

    skills = select_skills(m, spec)
    if skills:
        src_root = Path(m["paths"]["skills_dir"])
        (agent_dir / "skills").mkdir(mode=0o700)
        for s in skills:
            shutil.copytree(src_root / s, agent_dir / "skills" / s)

    auth_src = Path(m["harness"]["auth_source"])
    auth_dst = agent_dir / "auth.json"
    if m["harness"]["auth_mode"] == "symlink":
        os.symlink(auth_src, auth_dst)
    else:
        shutil.copyfile(auth_src, auth_dst)
        os.chmod(auth_dst, 0o600)
    return {"agent_dir": agent_dir, "servers": servers, "skills": skills}


def build_argv(m: dict, spec: dict, instruction_text: str,
               agent_dir: Path, sessions_dir: Path) -> list[str]:
    model = m["models"][spec["model"]]
    argv = [m["harness"]["binary"], "--mode", "json",
            "--no-extensions", "--no-context-files",
            "--no-prompt-templates", "--no-themes", "--no-approve",
            "--session-dir", str(sessions_dir),
            "--provider", model["provider"], "--model", model["id"],
            "--thinking", model.get("thinking", "medium"),
            "--no-skills"]
    for ext in ARM_EXTENSIONS[spec["mode"]]:
        argv += ["-e", ext]
    if spec["mode"] == "cli":
        argv += ["--no-mcp"]
        for s in select_skills(m, spec):
            argv += ["--skill", str(agent_dir / "skills" / s)]
    argv += ["--", instruction_text]
    return argv


# ---------------------------------------------------------------- pi run

class PiRun:
    """Stream one pi json-mode invocation to completion (or deadline).

    A watchdog thread enforces the deadline even when pi hangs without
    emitting output, so the runner never waits forever.
    """

    def __init__(self, argv: list[str], cwd: Path, env: dict,
                 events_path: Path, stderr_path: Path, deadline_s: int,
                 budget_tokens: int | None):
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.events_path = events_path
        self.stderr_path = stderr_path
        self.deadline_s = deadline_s
        self.budget_tokens = budget_tokens
        self.usage_total = 0
        self.assistant_ends: list[dict] = []
        self.settled = False
        self.session_header: dict | None = None
        self.killed_reason: str | None = None
        self.parse_errors = 0

    def _observe(self, rec: dict) -> None:
        t = rec.get("type")
        if t == "session":
            self.session_header = rec
        elif t == "message_end":
            msg = rec.get("message") or {}
            if msg.get("role") == "assistant":
                self.assistant_ends.append(msg)
                usage = msg.get("usage") or {}
                self.usage_total += int(usage.get("totalTokens") or 0)
        elif t == "agent_settled":
            self.settled = True

    def execute(self) -> None:
        with open(self.stderr_path, "ab") as err_fh:
            proc = subprocess.Popen(
                self.argv, cwd=str(self.cwd), env=self.env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err_fh,
                start_new_session=True, text=True, errors="replace",
            )
            watchdog = threading.Timer(
                self.deadline_s, self._watchdog, args=(proc,))
            watchdog.daemon = True
            watchdog.start()
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    with open(self.events_path, "a", encoding="utf-8") as fh:
                        fh.write(line + "\n")
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        self.parse_errors += 1
                        continue
                    self._observe(rec)
                    if (self.budget_tokens is not None
                            and self.usage_total > self.budget_tokens):
                        if not self.killed_reason:
                            self.killed_reason = "budget_exceeded"
                        _kill_group(proc)
                        break
            except KeyboardInterrupt:
                if not self.killed_reason:
                    self.killed_reason = "interrupted"
                _kill_group(proc)
                raise
            finally:
                watchdog.cancel()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if not self.killed_reason:
                        self.killed_reason = "deadline"
                    _kill_group(proc, force=True)
                    proc.wait(timeout=10)
        self.returncode = proc.returncode

    def _watchdog(self, proc: subprocess.Popen) -> None:
        if not self.killed_reason:
            self.killed_reason = "deadline"
        _kill_group(proc)

    def classify_stop(self) -> tuple[str, str | None]:
        """(status, detail) from structured event fields only."""
        if self.killed_reason == "deadline":
            return "timeout", f"deadline {self.deadline_s}s exceeded"
        if self.killed_reason == "budget_exceeded":
            return "incomplete", (f"budget {self.budget_tokens} tokens "
                                  f"exceeded at {self.usage_total}")
        if self.killed_reason == "interrupted":
            return "aborted", "runner interrupted"
        final = None
        for msg in reversed(self.assistant_ends):
            if msg.get("stopReason") != "pending":
                final = msg
                break
        if final is None:
            return ("infrastructure_error",
                    f"no completed assistant message; pi exit {self.returncode}")
        stop = final.get("stopReason")
        self.final_stop = stop
        detail_src = " ".join(
            str(final.get(k) or "") for k in
            ("errorMessage", "rawStopReason"))
        diagnostics = json.dumps(final.get("diagnostics") or [])
        if stop == "error":
            hay = (detail_src + " " + diagnostics).lower()
            if any(marker in hay for marker in QUOTA_MARKERS):
                return "provider_blocked", detail_src.strip() or "provider error"
            return "infrastructure_error", detail_src.strip() or stop
        if stop == "aborted":
            return "incomplete", "assistant aborted"
        if stop not in ("stop", "toolUse", "length", "deferred"):
            return "infrastructure_error", f"unexpected stopReason {stop!r}"
        if self.returncode != 0 and not self.settled:
            return ("infrastructure_error",
                    f"pi exit {self.returncode} without agent_settled")
        return "verify", ""


def _kill_group(proc: subprocess.Popen, force: bool = False) -> None:
    try:
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


# ---------------------------------------------------------------- verify

def run_verifier(m: dict, spec: dict, tdir: Path, workspace: Path,
                 env: dict) -> tuple[str, int]:
    task = m["tasks"][spec["task"]]
    places = {
        "workspace": str(workspace),
        "artifacts": str((workspace / task["artifacts"]).resolve()),
        "manifest_dir": manifest_dir_of(m),
        "rig_dir": str(Path(__file__).resolve().parent),
    }
    argv = [substitute(a, places) for a in task["verify"]]
    vdir = tdir / "private" / "verify"
    code, _out = run_cmd(argv, cwd=vdir, env=env,
                         timeout=task["verify_timeout_s"], out_dir=vdir,
                         tag="verifier")
    verdict = {0: "pass", 1: "incorrect", 2: "incomplete",
               3: "missing", 4: "verifier_error"}.get(code, "verifier_error")
    return verdict, code


# ---------------------------------------------------------------- campaign run

def run_campaign(m: dict, campaign: Campaign, state: dict, resume: bool) -> int:
    quota = m["quota"]
    instructions: dict[str, str] = {}
    exit_code = 0
    tried = 0
    # Each assigned trial is attempted once. Quota recovery waits before
    # pending work, never replaces the original failed attempt.
    work = [s["trial_id"] for s in state["plan"]]
    i = 0
    while i < len(work):
        t_id = work[i]
        trial = state["trials"][t_id]
        spec = trial["spec"]
        if trial["status"] in TERMINAL:
            i += 1
            continue
        if resume and trial["status"] == "running":
            trial["status"] = "aborted"
            trial["last_error"] = ("found running at resume; original attempt "
                                   "not replayed")
            campaign.save(state)
            campaign.log(f"{t_id}: marked aborted (interrupted original attempt)")
            i += 1
            continue
        provider = m["models"][spec["model"]]["provider"]
        wait = wait_for_provider(campaign, state, provider, quota)
        if wait is None:
            exit_code = 3
            break  # paused beyond policy; recover via run --resume
        tried += 1
        try:
            outcome = run_one_trial(m, campaign, state, trial, instructions)
        except StopCampaign as exc:
            campaign.log(f"CAMPAIGN STOPPED: {exc}")
            state["events"].append({"utc": zulu(now_utc()), "event": "stop",
                                    "reason": str(exc)})
            campaign.save(state)
            return 2
        if outcome == "provider_blocked":
            backoff = register_backoff(campaign, state, provider, quota, trial)
            if backoff is None:
                campaign.log(f"{t_id}: provider {provider} blocked; backoff "
                             "exceeds policy — pausing campaign (resume later)")
                exit_code = 3
                break
            campaign.log(f"{t_id}: original attempt retained as provider_blocked; "
                         f"pending work for {provider} waits {backoff:.0f}s")
        elif outcome == "infrastructure_error":
            campaign.log(f"{t_id}: infrastructure error — pausing for investigation")
            exit_code = 2
            break
        else:
            state["provider_backoff"].pop(provider, None)
        i += 1
    if tried == 0 and exit_code == 0:
        campaign.log("nothing to do: all trials terminal")
    finish = summary(state)
    campaign.log("summary: " + json.dumps(finish["by_status"], sort_keys=True))
    campaign.save(state)
    return exit_code


def wait_for_provider(campaign: Campaign, state: dict, provider: str,
                      quota: dict) -> float | None:
    """Block until provider backoff elapses. None => pause the campaign."""
    info = state["provider_backoff"].get(provider)
    if not info:
        return 0.0
    remaining = info["blocked_until"] - now_utc()
    probe = quota.get("probe_command")
    if remaining > 0 and probe:
        argv = [substitute(a, {"manifest_dir": manifest_dir_of(campaign.m)})
                for a in probe]
        penv = sanitized_env()
        while remaining > 0:
            code, _ = run_cmd(argv, cwd=campaign.dir, env=penv,
                              timeout=quota["probe_timeout_s"],
                              out_dir=campaign.dir / "probes", tag=f"{provider}")
            # A cheap auxiliary probe — never a task retry; success only
            # clears the wait, it does not touch trial outcomes.
            if code == 0:
                campaign.log(f"probe ok for {provider}; clearing backoff wait")
                return 0.0
            time.sleep(min(remaining, quota["probe_timeout_s"]))
            remaining = info["blocked_until"] - now_utc()
    if remaining > 0:
        if remaining > quota["pause_above_s"]:
            return None
        campaign.log(f"waiting {remaining:.0f}s for {provider} backoff")
        time.sleep(remaining)
    return remaining


def register_backoff(campaign: Campaign, state: dict, provider: str,
                     quota: dict, trial: dict) -> float | None:
    info = state["provider_backoff"].setdefault(
        provider, {"consecutive": 0, "blocked_until": 0})
    info["consecutive"] += 1
    backoff = min(quota["base_s"] * quota["multiplier"] ** (info["consecutive"] - 1),
                  quota["cap_s"])
    if backoff > quota["pause_above_s"]:
        info["blocked_until"] = now_utc() + backoff
        campaign.save(state)
        return None  # pause; resume recovers after blocked_until (or via probe)
    info["blocked_until"] = now_utc() + backoff
    campaign.save(state)
    return backoff


def summary(state: dict) -> dict:
    by_status: dict[str, int] = {}
    for t in state["trials"].values():
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
    return {"by_status": by_status,
            "total": len(state["trials"])}


def run_one_trial(m: dict, campaign: Campaign, state: dict, trial: dict,
                  instructions: dict) -> str:
    spec = trial["spec"]
    t_id = spec["trial_id"]
    task = m["tasks"][spec["task"]]
    base = campaign.trial_dir(t_id)
    # Attempt-scoped evidence directory. Automatic task replay is forbidden.
    attempt_no = trial["attempts"] + 1
    tdir = base / f"attempt-{attempt_no:03d}"
    if tdir.exists():  # defensive: terminal trials never reach here
        raise ManifestError(f"trial dir {tdir} already exists")
    tdir.mkdir(mode=0o700, parents=True)
    private = tdir / "private"
    private.mkdir(mode=0o700)
    workspace = tdir / "workspace"
    workspace.mkdir(mode=0o700)

    trial.update(status="running", attempts=attempt_no,
                 started_utc=zulu(now_utc()))
    campaign.save(state)

    # Pre-flight: auth, required executables and env names for enabled
    # pieces. Pass-through allowlist names are optional; capability/catalog
    # env_names are required.
    env_names: list[str] = list(m.get("env_pass_names", []))
    required_env: list[str] = []
    for name in select_catalog(m, spec):
        names = list(m["catalog"][name].get("env_names", []))
        env_names += names
        required_env += names
    if spec["mode"] == "cli":
        for c in select_capabilities(m, spec):
            names = list(m["capabilities"][c].get("env_names", []))
            env_names += names
            required_env += names
    missing_exec = [e for e in _required_executables(m, spec)
                    if not shutil.which(e)]
    missing_env = sorted({n for n in required_env if n not in os.environ})
    auth_ok = Path(m["harness"]["auth_source"]).is_file()
    if missing_exec or missing_env or not auth_ok:
        _finish_trial(campaign, state, trial, "infrastructure_error",
                      last_error=f"pre-flight failed: missing executables "
                      f"{missing_exec} missing env {missing_env} "
                      f"auth_present={auth_ok}")
        raise StopCampaign(f"{t_id}: pre-flight failed (executables "
                           f"{missing_exec}, env {missing_env}, "
                           f"auth_present={auth_ok})")

    # Reset + setup run as private side processes, outside the workspace.
    places = {"workspace": str(workspace),
              "artifacts": str((workspace / task["artifacts"]).resolve()),
              "manifest_dir": manifest_dir_of(m),
              "rig_dir": str(Path(__file__).resolve().parent)}
    agent_info = prepare_agent_dir(m, spec, trial, tdir)
    env, scrubbed = build_trial_env(
        m, env_names, agent_info["agent_dir"])
    trial["scrubbed_env_names"] = scrubbed
    for key, arr in (("reset", task.get("reset")), ("setup", task.get("setup"))):
        if arr:
            argv = [substitute(a, places) for a in arr]
            code, _ = run_cmd(argv, cwd=private / f"{key}-cwd", env=env,
                              timeout=task["setup_timeout_s"],
                              out_dir=private, tag=key)
            if code != 0:
                _finish_trial(campaign, state, trial, "infrastructure_error",
                              last_error=f"{key} exited {code}")
                raise StopCampaign(f"{t_id}: {key} command failed "
                                   f"(exit {code}); see {private}/{key}.log")

    # Agent-facing inputs: instruction text only. Verifier/reference
    # internals stay outside the workspace by construction.
    instr_path = str(Path(task["instruction"]))
    if instr_path not in instructions:
        instructions[instr_path] = Path(instr_path).read_text(encoding="utf-8")
    text = instructions[instr_path]
    (workspace / "instruction.md").write_text(text, encoding="utf-8")

    argv = build_argv(m, spec, text, agent_info["agent_dir"],
                      tdir / "sessions")
    (tdir / "sessions").mkdir(mode=0o700)
    trial["argv_flags"] = [a for a in argv[1:] if a != text]
    trial["prompt_sha256"] = hashlib.sha256(text.encode()).hexdigest()[:16]
    campaign.save(state)

    budget = m["budget"].get("max_total_tokens")
    pirun = PiRun(argv, cwd=workspace, env=env,
                  events_path=private / "events.jsonl",
                  stderr_path=private / "pi-stderr.log",
                  deadline_s=task["deadline_s"], budget_tokens=budget)
    campaign.log(f"{t_id} start: {spec['mode']}/{spec['model']} "
                 f"task={spec['task']} catalog={spec['catalog']} "
                 f"servers={agent_info['servers']} skills={agent_info['skills']}")
    try:
        pirun.execute()
    except KeyboardInterrupt:
        _finish_trial(campaign, state, trial, "aborted",
                      last_error="runner interrupted")
        raise
    trial["pi_exit_code"] = pirun.returncode
    trial["usage_total_tokens"] = pirun.usage_total
    status, detail = pirun.classify_stop()
    trial["stop_reason"] = getattr(pirun, "final_stop", None)
    if status != "verify":
        _finish_trial(campaign, state, trial, status, last_error=detail)
        return status
    if pirun.returncode != 0:
        trial["notes"].append(f"pi exited {pirun.returncode} after a settled run")
    verdict, vcode = run_verifier(m, spec, tdir, workspace, env)
    trial["verifier_exit_code"] = vcode
    _finish_trial(campaign, state, trial, verdict)
    return verdict


def _required_executables(m: dict, spec: dict) -> list[str]:
    req: list[str] = []
    for name in select_catalog(m, spec):
        cmd = m["catalog"][name].get("command")
        if cmd:
            req.append(Path(cmd if not cmd.startswith("~/") else
                            Path.home() / cmd[2:]).name)
    if spec["mode"] == "cli":
        for c in select_capabilities(m, spec):
            req += m["capabilities"][c]["executables"]
    return sorted(set(req))


def _finish_trial(campaign: Campaign, state: dict, trial: dict,
                  status: str, last_error: str | None = None) -> None:
    assert status in TERMINAL
    trial["status"] = status
    trial["ended_utc"] = zulu(now_utc())
    if last_error:
        trial["last_error"] = last_error
    campaign.save(state)
    # Per-trial durable record, private dir (0700), outside the workspace.
    atomic_write_json(campaign.trial_dir(trial["spec"]["trial_id"])
                      / f"attempt-{trial['attempts']:03d}" / "private"
                      / "trial.json", trial)
    campaign.log(f"{trial['spec']['trial_id']}: {status}"
                 + (f" ({last_error})" if last_error else ""))


# ---------------------------------------------------------------- CLI cmds

def cmd_validate(args) -> int:
    m = load_manifest(Path(args.manifest))
    errors = validate_manifest(m)
    print(f"manifest: {args.manifest}")
    print(f"campaign_id: {m['harness'].get('campaign_id')}")
    print(f"models: " + ", ".join(
        f"{k}={v['provider']}/{v['id']}" for k, v in m.get("models", {}).items()))
    print(f"matrix: modes={m['matrix']['modes']} catalogs="
          f"{m['matrix']['catalogs']} reps={m['matrix']['reps']} "
          f"seed={m['matrix']['seed']}")
    plan = build_plan(m)
    print(f"plan: {len(plan)} trials")
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("static checks: OK")
    print("readiness:")
    bin_ok = Path(m["harness"]["binary"]).is_file()
    print(f"  harness binary present: {bin_ok} "
          f"(required version {m['harness'].get('required_version') or 'any'})")
    print(f"  auth source present: {Path(m['harness']['auth_source']).is_file()} "
          "(contents never read or printed)")
    missing = sorted({e for spec in plan
                      for e in _required_executables(m, spec)
                      if not shutil.which(e)})
    print(f"  executables missing from PATH: {missing or 'none'}")
    env_names = sorted({n for t in m["tasks"].values()
                        for n in [x for c in t["capabilities"]
                                  for x in m["capabilities"][c].get("env_names", [])
                                  ] + [x for c in t["catalog"]
                                       for x in m["catalog"][c].get("env_names", [])]})
    have = [n for n in env_names if n in os.environ]
    print(f"  capability env names present: {have} / required {env_names}")
    print("  OS sandbox: NOT CONFIGURED — same-user isolation is config "
          "discovery isolation only, not a credential boundary; privileged "
          "environment validation is pending.")
    print("  route compliance: audited separately from transcripts; verifier "
          "pass alone is not research success.")
    return 0


def cmd_plan(args) -> int:
    m = load_manifest(Path(args.manifest))
    errors = validate_manifest(m)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    plan = build_plan(m)
    digest = sha256_json({"manifest": m, "plan": plan})
    print(f"digest {digest}")
    for s in plan:
        print(f"{s['trial_id']}  task={s['task']:<28} catalog={s['catalog']:<8} "
              f"mode={s['mode']:<8} model={s['model']:<12} rep={s['rep']}")
    if args.write:
        atomic_write_json(Path(args.write), {"digest": digest, "plan": plan})
        print(f"wrote {args.write}")
    return 0


def cmd_status(args) -> int:
    campaign = Campaign(Path(args.manifest))
    if not campaign.state_path.is_file():
        print(f"no campaign state at {campaign.state_path}")
        return 1
    state = json.loads(campaign.state_path.read_text(encoding="utf-8"))
    print(f"campaign {campaign.dir}  digest {state['digest'][:19]}…")
    print(f"{'trial':<6} {'status':<21} {'task':<28} {'mode':<8} "
          f"{'model':<12} {'rep':>3}  note")
    for spec in state["plan"]:
        t = state["trials"][spec["trial_id"]]
        note = (t.get("last_error") or "")[:60]
        print(f"{spec['trial_id']:<6} {t['status']:<21} {spec['task']:<28} "
              f"{spec['mode']:<8} {spec['model']:<12} {spec['rep']:>3}  {note}")
    print("summary: " + json.dumps(summary(state)["by_status"], sort_keys=True))
    return 0


def cmd_run(args) -> int:
    campaign = Campaign(Path(args.manifest))
    resuming = campaign.state_path.is_file()
    state = campaign.load_or_init()
    if resuming:
        campaign.log(f"resuming campaign (digest {campaign.digest[:19]}…)")
    return run_campaign(campaign.m, campaign, state, resume=resuming)


def cmd_doctor(args) -> int:
    """Live readiness checks without any model spend."""
    m = load_manifest(Path(args.manifest))
    errors = validate_manifest(m)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    binary = m["harness"]["binary"]
    try:
        out = subprocess.run([binary, "--version"], capture_output=True,
                             text=True, timeout=30)
        lines = out.stdout.strip().splitlines()
        if not lines:
            print(f"harness --version produced no output "
                  f"(exit {out.returncode}); stderr: "
                  f"{out.stderr.strip()[:200]}")
            return 1
        version = lines[-1].strip()
        req = m["harness"].get("required_version")
        ok = (req is None) or (req == version)
        print(f"pi version: {version} (required {req}) -> "
              f"{'OK' if ok else 'MISMATCH'}")
        if not ok:
            return 1
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"cannot execute harness: {exc}")
        return 1
    auth = Path(m["harness"]["auth_source"])
    print(f"auth source: {'present' if auth.is_file() else 'MISSING'} "
          f"(mode {m['harness']['auth_mode']}; contents never read)")
    if args.probe_mcp:
        return _doctor_probe_mcp(m)
    return 0


def _doctor_probe_mcp(m: dict) -> int:
    """Config-discovery probe: `pi mcp list` per MCP arm in a scratch dir.

    Spawns configured MCP servers (no model calls). Verifies that generated
    catalogs are discovered and that a poisoned ancestor .pi is ignored (the
    scratch project is untrusted in the fresh agent dir; pi mcp list reads
    ProjectTrustStore itself). npx-based servers may download packages on
    first run.
    """
    rc = 0
    for mode in ("eager", "deferred"):
        if mode not in m["matrix"]["modes"]:
            continue
        with tempfile.TemporaryDirectory(prefix="pi-doctor-") as tmp:
            scratch = Path(tmp)
            agent = scratch / "agent-dir"
            spec = {"mode": mode, "task": sorted(m["tasks"])[0],
                    "catalog": "full", "model": sorted(m["matrix"]["models"])[0]}
            poisoned = scratch / "poison"
            (poisoned / ".pi").mkdir(parents=True)
            (poisoned / ".pi" / "mcp.json").write_text(json.dumps(
                {"mcpServers": {"poisoned-ancestor-server": {"command": "false"}}}))
            prepare_agent_dir(m, spec, {"attempts": 0}, scratch)
            env, _ = build_trial_env(m, [], agent)
            proc = subprocess.run(
                [m["harness"]["binary"], "mcp", "list"],
                cwd=str(poisoned), env=env, capture_output=True, text=True,
                timeout=300)
            text = proc.stdout + proc.stderr
            want = select_catalog(m, spec)
            got_poison = "poisoned-ancestor-server" in text
            print(f"[{mode}] pi mcp list exit {proc.returncode}")
            for name in want:
                found = name in text
                print(f"  catalog server {name}: "
                      f"{'discovered' if found else 'NOT DISCOVERED'}")
                rc |= 0 if found else 1
            print(f"  poisoned ancestor server ignored: {not got_poison}")
            rc |= 0 if not got_poison else 1
    return rc


def cmd_trial(args) -> int:
    """Single ad-hoc trial without a manifest file (smoke testing)."""
    m = _trial_manifest(args)
    errors = validate_manifest(m)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    campaign = Campaign(Path("<trial>"), manifest_dict=m)
    state = campaign.load_or_init()
    return run_campaign(m, campaign, state, resume=False)


def _trial_manifest(args) -> dict:
    for name, _ in args.catalog_def:
        if name not in args.catalog:
            raise ManifestError(f"--catalog-def {name} has no matching --catalog")
    m = {
        "schema_version": SCHEMA_VERSION,
        "harness": {"campaign_id": args.campaign_id,
                    "binary": args.harness,
                    "auth_source": args.auth,
                    "auth_mode": args.auth_mode,
                    "required_version": args.required_version,
                    "env": {}},
        "models": {"m": {"provider": args.provider, "id": args.model,
                           "thinking": args.thinking}},
        "catalog": {name: json.loads(js)
                    for name, js in args.catalog_def},
        "capabilities": {c: {"kind": "cli", "skills": [c],
                               "executables": [c]}
                         for c in args.capability},
        "tasks": {"t": {"instruction": str(Path(args.instruction).resolve()),
                          "deadline_s": args.deadline,
                          "verify": shlex.split(args.verify),
                          "catalog": list(args.catalog),
                          "capabilities": list(args.capability),
                          "artifacts": ".", "setup": None, "reset": None,
                          "verify_timeout_s": 120, "setup_timeout_s": 300}},
        "matrix": {"modes": [args.mode], "models": ["m"], "reps": 1,
                     "seed": 0, "catalogs": ["required"]},
        "paths": {"skills_dir": str(Path(args.skills_dir).resolve()),
                    "run_root": str(Path(args.run_root).expanduser())},
        "env_pass_names": list(args.env_pass),
        "quota": dict(DEFAULT_QUOTA),
        "budget": {},
    }
    m = normalize_manifest(Path("<trial>"), m)
    m["paths"]["_manifest_dir"] = str(Path(args.instruction).resolve().parent)
    return m


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="runner.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="static manifest checks + readiness")
    p.add_argument("manifest")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("plan", help="print deterministic plan + digest")
    p.add_argument("manifest")
    p.add_argument("--write", help="write plan JSON to this path")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("run", help="run (or continue) the campaign")
    p.add_argument("manifest")
    p.add_argument("--resume", action="store_true",
                   help="explicit resume; interrupted running trials are "
                        "marked aborted, never replayed")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("resume", help="alias of run --resume")
    p.add_argument("manifest")
    p.set_defaults(fn=lambda a: cmd_run(argparse.Namespace(manifest=a.manifest,
                                                           resume=True)))

    p = sub.add_parser("status", help="show per-trial status")
    p.add_argument("manifest")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("doctor", help="live checks: version, auth presence, "
                       "config discovery (no model spend)")
    p.add_argument("manifest")
    p.add_argument("--probe-mcp", action="store_true",
                   help="also run `pi mcp list` (spawns MCP servers; npx may "
                        "download)")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("trial", help="single ad-hoc trial (smoke)")
    p.add_argument("--harness", required=True)
    p.add_argument("--required-version")
    p.add_argument("--auth", required=True)
    p.add_argument("--auth-mode", choices=("symlink", "copy"),
                   default="symlink")
    p.add_argument("--mode", choices=MODES, required=True)
    p.add_argument("--provider", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--thinking", default="medium")
    p.add_argument("--instruction", required=True)
    p.add_argument("--deadline", type=int, required=True)
    p.add_argument("--verify", required=True,
                   help="verifier command string (shlex-split)")
    p.add_argument("--capability", action="append", default=[],
                   help="capability id (repeatable)")
    p.add_argument("--catalog", action="append", default=[],
                   help="MCP catalog id (repeatable)")
    p.add_argument("--catalog-def", action="append", nargs=2, default=[],
                   metavar=("ID", "JSON"),
                   help="catalog entry definition as JSON")
    p.add_argument("--skills-dir", default=str(Path(__file__).resolve().parent
                                               / "skills"))
    p.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT))
    p.add_argument("--campaign-id", default="adhoc-trial")
    p.add_argument("--env-pass", action="append", default=[])
    p.set_defaults(fn=cmd_trial)

    args = ap.parse_args(argv)
    if getattr(args, "manifest", None):
        # stash manifest dir for path resolution in helpers
        m_path = Path(args.manifest).resolve()
        if not m_path.is_file():
            print(f"manifest not found: {m_path}", file=sys.stderr)
            return 1
    try:
        rc = args.fn(args)
    except ManifestError as exc:
        print(f"MANIFEST ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    return rc


if __name__ == "__main__":
    sys.exit(main())
