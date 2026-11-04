"""Status classification, deadline, setup/verify failure, quota backoff,
and resume semantics — all against the FAKE pi (offline) [ours]."""
import json
import os
import time
import unittest
from pathlib import Path

from rig_common import Rig

OK_ART = {"FAKE_ARTIFACT": "__CWD__/result.json"}


class TestStatuses(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.cleanup)

    def manifest(self, **kw):
        return self.rig.write_manifest(modes=("eager",), models=("luna",),
                                       **kw)

    def run_cli(self, manifest, expect_rc=None, env_extra=None):
        return self.rig.run_runner(["run", str(manifest)],
                                   env_extra={**OK_ART, **(env_extra or {})},
                                   expect_rc=expect_rc)

    def status(self, campaign_id="test-campaign"):
        return self.rig.campaign_state(campaign_id)["trials"]["t0001"]

    def test_assistant_error_with_exit0_detected(self):
        self.rig.scenario = "assistant_error"
        m = self.manifest(deadline=30)
        self.run_cli(m, expect_rc=2)
        t = self.status()
        self.assertEqual(t["status"], "infrastructure_error")
        self.assertEqual(t["stop_reason"], "error")
        self.assertIn("provider exploded", t["last_error"])
        self.assertEqual(t["pi_exit_code"], 0,
                         "stopReason=error must be caught despite exit 0")

    def test_quota_error_maps_to_provider_blocked(self):
        self.rig.scenario = "quota"
        m = self.manifest(deadline=30,
                          quota={"base_s": 1, "cap_s": 2, "pause_above_s": 5,
                                 "max_attempts_per_trial": 1})
        self.run_cli(m, expect_rc=0)
        t = self.status()
        self.assertEqual(t["status"], "provider_blocked")
        self.assertEqual(t["attempts"], 1)
        state = self.rig.campaign_state()
        self.assertIn("fake", state["provider_backoff"])

    def test_quota_never_replays_original_trial(self):
        self.rig.scenario = "quota_then_ok"
        m = self.manifest(deadline=30,
                          quota={"base_s": 1, "cap_s": 2, "pause_above_s": 5,
                                 "max_attempts_per_trial": 1})
        self.run_cli(m, expect_rc=0)
        self.rig.scenario = "ok"
        self.rig.run_runner(["resume", str(m)], env_extra=OK_ART, expect_rc=0)
        t = self.status()
        self.assertEqual(t["status"], "provider_blocked")
        self.assertEqual(t["attempts"], 1)

    def test_quota_wait_continues_next_trial_not_original(self):
        self.rig.scenario = "quota_then_ok"
        m = self.rig.write_manifest(modes=("eager", "deferred"), models=("luna",),
            quota={"base_s": 1, "cap_s": 2, "pause_above_s": 5,
                   "max_attempts_per_trial": 1})
        self.run_cli(m, expect_rc=0)
        trials = list(self.rig.campaign_state()["trials"].values())
        self.assertEqual([t["status"] for t in trials], ["provider_blocked", "pass"])
        self.assertEqual([t["attempts"] for t in trials], [1, 1])

    def test_changed_instruction_rejected_on_resume(self):
        m = self.manifest()
        self.run_cli(m, expect_rc=0)
        self.rig.instruction.write_text("Changed after campaign started")
        proc = self.rig.run_runner(["resume", str(m)])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("frozen manifest changed", proc.stderr)

    def test_quota_pause_recovers_across_restart(self):
        self.rig.scenario = "quota"
        m = self.manifest(deadline=30,
                          quota={"base_s": 3, "cap_s": 3600,
                                 "pause_above_s": 2,
                                 "max_attempts_per_trial": 1})
        proc = self.run_cli(m, expect_rc=3)
        self.assertIn("pausing", proc.stdout)
        state = self.rig.campaign_state()
        self.assertEqual(state["trials"]["t0001"]["status"],
                         "provider_blocked")
        blocked_until = state["provider_backoff"]["fake"]["blocked_until"]
        self.assertGreater(blocked_until, time.time())
        # Simulate quota reset, then resume; fake succeeds on a later attempt.
        state["provider_backoff"]["fake"]["blocked_until"] = 0
        (self.rig.run_root / "test-campaign" / "campaign.json").write_text(
            json.dumps(state))
        self.rig.scenario = "ok"
        self.rig.run_runner(["run", "--resume", str(m)], env_extra=OK_ART,
                            expect_rc=0)
        self.assertEqual(self.status()["status"], "provider_blocked")
        self.assertEqual(self.status()["attempts"], 1)

    def test_timeout(self):
        self.rig.scenario = "hang"
        m = self.manifest(deadline=2)
        self.run_cli(m, expect_rc=0)
        t = self.status()
        self.assertEqual(t["status"], "timeout")

    def test_budget_kill(self):
        self.rig.scenario = "ok"
        m = self.manifest(deadline=30, budget={"max_total_tokens": 10})
        self.run_cli(m, expect_rc=0)
        t = self.status()
        self.assertEqual(t["status"], "incomplete")
        self.assertIn("budget", t["last_error"])

    def test_harness_exit_without_settled(self):
        self.rig.scenario = "exit7"
        m = self.manifest(deadline=30)
        self.run_cli(m, expect_rc=2)
        t = self.status()
        self.assertEqual(t["status"], "infrastructure_error")
        self.assertEqual(t["pi_exit_code"], 7)

    def test_verifier_incorrect(self):
        self.rig.scenario = "ok"
        m = self.manifest(deadline=30, verify_exit=1)
        self.run_cli(m, expect_rc=0)
        self.assertEqual(self.status()["status"], "incorrect")

    def test_verifier_error(self):
        self.rig.scenario = "ok"
        m = self.manifest(deadline=30, verify_exit=4)
        self.run_cli(m, expect_rc=0)
        self.assertEqual(self.status()["status"], "verifier_error")

    def test_setup_failure_stops_campaign(self):
        p = self.manifest(deadline=30)
        text = p.read_text().replace(
            "[tasks.t1]",
            '[tasks.t1]\nsetup = ["sh", "-c", "echo setup-broken >&2; exit 3"]')
        p.write_text(text)
        proc = self.run_cli(p, expect_rc=2)
        self.assertIn("CAMPAIGN STOPPED", proc.stdout)
        self.assertEqual(self.status()["status"], "infrastructure_error")
        tdir = (self.rig.run_root / "test-campaign" / "trials" / "t0001" / "attempt-001")
        self.assertTrue((tdir / "private" / "setup.log").is_file())
        self.assertIn("setup-broken", (tdir / "private" / "setup.log")
                      .read_text())

    def test_setup_runs_outside_agent_workspace(self):
        """Setup output must not leak into the agent-visible workspace."""
        p = self.manifest(deadline=30)
        text = p.read_text().replace(
            "[tasks.t1]",
            '[tasks.t1]\nsetup = ["sh", "-c", "pwd > setup-cwd.txt; echo secret-reference > reference-answer.txt"]')
        p.write_text(text)
        self.run_cli(p, expect_rc=0)
        tdir = (self.rig.run_root / "test-campaign" / "trials" / "t0001" / "attempt-001")
        ws = tdir / "workspace"
        self.assertEqual(ws.name, "workspace")
        self.assertNotIn("reference-answer.txt",
                         [x.name for x in ws.iterdir()])
        self.assertTrue((tdir / "private" / "setup-cwd" /
                         "setup-cwd.txt").is_file())

    def test_resume_marks_interrupted_running_aborted(self):
        self.rig.scenario = "ok"
        m = self.manifest(deadline=30)
        self.rig.run_runner(["run", str(m)], env_extra=OK_ART, expect_rc=0)
        state = self.rig.campaign_state()
        # Simulate a crash during a later trial (add one "running").
        state["trials"]["t0002"] = dict(
            state["trials"]["t0001"], status="running", spec={
                "task": "t1", "catalog": "required", "mode": "eager",
                "model": "luna", "rep": 1, "trial_id": "t0002"})
        del state["trials"]["t0001"]
        state["plan"].append(state["trials"]["t0002"]["spec"])
        state["plan"] = [s for s in state["plan"] if s["trial_id"] != "t0001"]
        (self.rig.run_root / "test-campaign" / "campaign.json").write_text(
            json.dumps(state))
        self.rig.run_runner(["run", "--resume", str(m)], env_extra=OK_ART,
                            expect_rc=0)
        state2 = self.rig.campaign_state()
        t2 = state2["trials"]["t0002"]
        self.assertEqual(t2["status"], "aborted")
        self.assertIn("not replayed", t2["last_error"])
        self.assertEqual(t2["attempts"], 1,
                         "interrupted original attempt must not be replayed")

    def test_status_command(self):
        self.rig.scenario = "ok"
        m = self.manifest(deadline=30)
        self.run_cli(m, expect_rc=0)
        proc = self.rig.run_runner(["status", str(m)], expect_rc=0)
        self.assertIn("t0001", proc.stdout)
        self.assertIn("pass", proc.stdout)


if __name__ == "__main__":
    unittest.main()
