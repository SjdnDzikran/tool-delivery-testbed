"""Shared helpers for offline runner tests [ours].

Builds a synthetic rig (skills dir with a ponytail decoy, fake auth file,
fake pi harness) and manifests. No network, no model spend.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

RIG = Path(__file__).resolve().parents[1]
RUNNER = RIG / "runner.py"
TESTS = Path(__file__).resolve().parent

sys.path.insert(0, str(RIG))
import runner  # noqa: E402

PONYTAIL_DECOY = """---
name: ponytail
description: Personal global skill that must never reach a trial agent.
---

# ponytail decoy
"""

TASK_SKILL = """---
name: fake-gh
description: Task-neutral GitHub CLI notes for the synthetic rig.
---

Use `gh` and `git` per the task instruction.
"""


def toml_inline(d: dict) -> str:
    """TOML inline table (json.dumps uses ':' which TOML rejects)."""
    return "{" + ", ".join(f"{k} = {json.dumps(v)}" for k, v in d.items()) + "}"


class Rig:
    """Synthetic environment: fake harness, auth, skills, instructions."""

    def __init__(self, scenario: str = "ok"):
        self.root = Path(tempfile.mkdtemp(prefix="rig-test-"))
        self.skills = self.root / "skills"
        (self.skills / "fake-gh").mkdir(parents=True)
        (self.skills / "fake-gh" / "SKILL.md").write_text(TASK_SKILL)
        (self.skills / "ponytail").mkdir()
        (self.skills / "ponytail" / "SKILL.md").write_text(PONYTAIL_DECOY)
        self.auth = self.root / "auth.json"
        self.auth.write_text('{"fake": {"type": "api_key", "key": "sk-FAKE"}}')
        os.chmod(self.auth, 0o600)
        self.fake_pi = self.root / "fake-pi.sh"
        shutil_copy(TESTS / "fake_pi.sh", self.fake_pi)
        self.fake_pi.chmod(0o755)
        self.fake_verify = self.root / "fake_verify.py"
        shutil_copy(TESTS / "fake_verify.py", self.fake_verify)
        self.instruction = self.root / "instruction.md"
        self.instruction.write_text("Do the fake task. Write result.json.")
        self.scenario = scenario
        self.state = self.root / "fake-state"
        self.dump = self.root / "dump"
        self.run_root = self.root / "runs"

    def manifest(self, *, modes=("eager", "deferred", "cli"),
                 models=("luna",), catalog=("srv",),
                 verify_exit=None, quota=None, budget=None, seed=7,
                 campaign_id="test-campaign", task_catalog=None,
                 catalogs=("required",), deadline=30) -> str:
        """Render a TOML manifest. json.dumps emits TOML-compatible
        strings/arrays/numbers for every value used here."""
        verify = [sys.executable, str(self.fake_verify), "--artifacts",
                  "{artifacts}"]
        if verify_exit is not None:
            verify = [sys.executable, "-c",
                      f"import os,sys;sys.exit({verify_exit})"]
        caps = os.environ.get("FAKE_TEST_CAPS", "gh").split(",")
        j = json.dumps
        lines = [
            "schema_version = 1",
            "env_pass_names = " + j(
                ["FAKE_PI_DUMP", "FAKE_SCENARIO", "FAKE_STATE",
                 "FAKE_ARTIFACT", "FAKE_SLEEP"]),
            "[harness]",
            f"campaign_id = {j(campaign_id)}",
            f"binary = {j(str(self.fake_pi))}",
            f"required_version = {j('0.0.0-fake')}",
            f"auth_source = {j(str(self.auth))}",
            'auth_mode = "symlink"',
            "[harness.env]",
            'PI_OFFLINE = "1"',
            "[models.luna]",
            'provider = "fake"',
            'id = "fake-model-1"',
            'thinking = "medium"',
            "[models.glm]",
            'provider = "fake"',
            'id = "fake-model-2"',
            'thinking = "low"',
            "[capabilities.gh]",
            'kind = "cli"',
            f"skills = {j(['fake-gh'])}",
            f"executables = {j(['sh'])}",
            f"env_names = {j(['FAKE_TEST_TOKEN'])}",
            "[catalog.srv]",
            'command = "sh"',
            f"args = {j(['-c', 'sleep 30'])}",
            "timeout = 1",
            f"env = {toml_inline({'FAKE_TEST_TOKEN': '${FAKE_TEST_TOKEN}'})}",
            f"env_names = {j(['FAKE_TEST_TOKEN'])}",
            "[tasks.t1]",
            f"instruction = {j(str(self.instruction))}",
            f"capabilities = {j(caps)}",
            f"catalog = {j(list(task_catalog if task_catalog is not None else catalog))}",
            f"deadline_s = {deadline}",
            f"verify = {j(verify)}",
            "[paths]",
            f"skills_dir = {j(str(self.skills))}",
            f"run_root = {j(str(self.run_root))}",
            "[matrix]",
            f"modes = {j(list(modes))}",
            f"models = {j(list(models))}",
            f"catalogs = {j(list(catalogs))}",
            "reps = 1",
            f"seed = {seed}",
        ]
        if quota:
            lines.append("[quota]")
            lines += [f"{k} = {j(v)}" for k, v in quota.items()]
        if budget:
            lines.append("[budget]")
            lines += [f"{k} = {j(v)}" for k, v in budget.items()]
        return "\n".join(lines) + "\n"

    def write_manifest(self, **kw) -> Path:
        p = self.root / "manifest.toml"
        p.write_text(self.manifest(**kw), encoding="utf-8")
        return p

    def env(self, **extra) -> dict:
        e = {k: v for k, v in os.environ.items()
             if k not in ("OPENAI_API_KEY", "FAKE_SECRET_SHOULD_SCRUB")}
        e.update({
            "FAKE_PI_DUMP": str(self.dump),
            "FAKE_SCENARIO": self.scenario,
            "FAKE_STATE": str(self.state),
            "FAKE_ARTIFACT": "",  # set by caller when needed
            "FAKE_TEST_TOKEN": "fake-token-value",
            "FAKE_SECRET_SHOULD_SCRUB": "x",  # not in scrub lists; pass test uses allowlist
        })
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def run_runner(self, argv: list[str], env_extra: dict | None = None,
                   expect_rc=None) -> subprocess.CompletedProcess:
        env = self.env()
        if env_extra:
            env.update({k: str(v) for k, v in env_extra.items()})
        proc = subprocess.run([sys.executable, str(RUNNER), *argv],
                              env=env, capture_output=True, text=True,
                              timeout=300)
        if expect_rc is not None:
            assert proc.returncode == expect_rc, (
                f"rc={proc.returncode}\nSTDOUT{proc.stdout}\nSTDERR{proc.stderr}")
        return proc

    def campaign_state(self, campaign_id="test-campaign") -> dict:
        p = self.run_root / campaign_id / "campaign.json"
        return json.loads(p.read_text())

    def cleanup(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)


def shutil_copy(src: Path, dst: Path) -> None:
    dst.write_text(src.read_text())


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)
