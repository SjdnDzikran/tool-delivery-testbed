"""End-to-end single-trial tests against the FAKE pi executable [ours].

Verifies recorded argv/env/cwd: explicit isolation flags reach the harness,
env scrubbing works, the workspace is the agent cwd, artifacts land there,
and statuses classify correctly. No model spend, no network.
"""
import json
import os
import unittest
from pathlib import Path

from rig_common import Rig, mode_of


class TestTrialEndToEnd(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(scenario="ok")
        self.addCleanup(self.rig.cleanup)
        self.manifest = self.rig.write_manifest(
            modes=("eager",), models=("luna",), deadline=60)

    def run_ok(self, extra_env=None):
        env_extra = {"FAKE_ARTIFACT": ""}
        # fake pi writes the artifact into its cwd; tell it via a marker:
        env_extra["FAKE_ARTIFACT"] = "__CWD__/result.json"
        if extra_env:
            env_extra.update(extra_env)
        proc = self.rig.run_runner(["run", str(self.manifest)],
                                   env_extra=env_extra, expect_rc=0)
        return proc

    def read_dump(self, name) -> str:
        return (self.rig.dump / name).read_text()

    def test_passing_trial_records_and_artifacts(self):
        self.run_ok()
        state = self.rig.campaign_state()
        trial = state["trials"]["t0001"]
        self.assertEqual(trial["status"], "pass")
        self.assertEqual(trial["usage_total_tokens"], 15)
        tdir = self.rig.run_root / "test-campaign" / "trials" / "t0001" / "attempt-001"
        # cwd was the agent workspace
        self.assertEqual(Path(self.read_dump("cwd.txt").strip()),
                         tdir / "workspace")
        # instruction copied, only instruction (no verifier internals)
        self.assertTrue((tdir / "workspace" / "instruction.md").is_file())
        self.assertTrue((tdir / "workspace" / "result.json").is_file())
        # events + stderr + trial record stored outside the workspace
        self.assertTrue((tdir / "private" / "events.jsonl").is_file())
        self.assertTrue((tdir / "private" / "pi-stderr.log").is_file())
        self.assertTrue((tdir / "private" / "trial.json").is_file())
        self.assertFalse((tdir / "workspace" / "trial.json").exists())
        # sessions persisted (persistent sessions, no --no-session)
        self.assertTrue((tdir / "sessions").is_dir())
        argv = self.read_dump("argv.txt").splitlines()
        self.assertNotIn("--no-session", argv)
        self.assertIn("--session-dir", argv)

    def test_env_isolation(self):
        self.run_ok(extra_env={
            "OPENAI_API_KEY": "sk-LEAK", "ANTHROPIC_API_KEY": "sk-LEAK",
            "ZAI_API_KEY": "leak", "PI_CODING_AGENT_DIR": "/leak",
            "PI_OFFLINE": "0",
        })
        envtext = self.read_dump("env.txt")
        env = dict(line.split("=", 1) for line in envtext.splitlines()
                   if "=" in line)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ZAI_API_KEY", env)
        self.assertNotIn("FAKE_SECRET_SHOULD_SCRUB", env)  # not allowlisted
        self.assertIn("FAKE_TEST_TOKEN", env)  # capability env allowlisted
        tdir = self.rig.run_root / "test-campaign" / "trials" / "t0001" / "attempt-001"
        self.assertEqual(env["PI_CODING_AGENT_DIR"],
                         str(tdir / "agent-dir"))
        self.assertEqual(env["PI_SKIP_VERSION_CHECK"], "1")
        self.assertEqual(env["PI_OFFLINE"], "1")  # harness.env wins
        self.assertNotIn("PI_CODING_AGENT_SESSION_DIR", env)
        state = self.rig.campaign_state()
        scrubbed = state["trials"]["t0001"]["scrubbed_env_names"]
        self.assertIn("OPENAI_API_KEY", scrubbed)
        self.assertIn("PI_CODING_AGENT_DIR", scrubbed)
        # scrubbed names only — never values
        self.assertNotIn("sk-LEAK", json.dumps(state))

    def test_cli_arm_flags_reach_harness(self):
        m = self.rig.write_manifest(modes=("cli",), models=("luna",))
        self.rig.run_runner(["run", str(m)],
                            env_extra={"FAKE_ARTIFACT": "__CWD__/result.json"},
                            expect_rc=0)
        argv = self.read_dump("argv.txt").splitlines()
        self.assertIn("--no-mcp", argv)
        self.assertIn("--no-skills", argv)
        skills = [argv[i + 1] for i, v in enumerate(argv) if v == "--skill"]
        self.assertEqual(len(skills), 1)
        self.assertIn("fake-gh", skills[0])
        self.assertNotIn("-e", argv)

    def test_deferred_arm_flags_reach_harness(self):
        m = self.rig.write_manifest(modes=("deferred",), models=("luna",))
        self.rig.run_runner(["run", str(m)],
                            env_extra={"FAKE_ARTIFACT": "__CWD__/result.json"},
                            expect_rc=0)
        argv = self.read_dump("argv.txt").splitlines()
        exts = [argv[i + 1] for i, v in enumerate(argv) if v == "-e"]
        self.assertEqual(exts, ["builtin:mcp", "builtin:tool-search"])

    def test_digest_frozen_and_idempotent(self):
        self.run_ok()
        state1 = self.rig.campaign_state()
        self.rig.run_runner(["run", str(self.manifest)], expect_rc=0)
        state2 = self.rig.campaign_state()
        self.assertEqual(state1["digest"], state2["digest"])
        self.assertEqual(state2["trials"]["t0001"]["status"], "pass",
                         "completed trials must not be overwritten")
        # manifest change under the same campaign_id is refused
        self.rig.write_manifest(modes=("deferred",), models=("luna",))
        proc = self.rig.run_runner(["run", str(self.manifest)])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("frozen", proc.stderr)


if __name__ == "__main__":
    unittest.main()
