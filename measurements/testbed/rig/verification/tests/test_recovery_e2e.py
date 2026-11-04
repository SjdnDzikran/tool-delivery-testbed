"""End-to-end quota/fault-recovery verification through runner.py with the
rig's fake Pi [ours — offline, deterministic fault injection].

Covers: zero-exit assistant provider errors, quota backoff before pending
work, pause beyond policy, resume across restart, original-failure
retention (no replay), running→aborted on resume, probe_command clearing a
wait. Complements rig/tests/test_statuses.py at CLI process level.
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from rig_common import Rig  # noqa: E402

OK_ART = {"FAKE_ARTIFACT": "__CWD__/result.json"}


class TestRecoveryE2E(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.cleanup)

    def state(self):
        return self.rig.campaign_state()

    def test_provider_error_stops_campaign_and_keeps_original(self):
        self.rig.scenario = "assistant_error"
        m = self.rig.write_manifest(modes=("eager", "deferred"),
                                    models=("luna",), deadline=30)
        proc = self.rig.run_runner(["run", str(m)], env_extra=OK_ART)
        self.assertEqual(proc.returncode, 2)
        trials = self.state()["trials"]
        self.assertEqual(trials["t0001"]["status"], "infrastructure_error")
        self.assertEqual(trials["t0001"]["stop_reason"], "error")
        self.assertEqual(trials["t0001"]["attempts"], 1)
        self.assertEqual(trials["t0002"]["status"], "pending")
        # resume never replays the failed trial
        self.rig.scenario = "ok"
        proc = self.rig.run_runner(["run", "--resume", str(m)],
                                   env_extra=OK_ART)
        self.assertEqual(proc.returncode, 0)
        trials = self.state()["trials"]
        self.assertEqual(trials["t0001"]["status"], "infrastructure_error")
        self.assertEqual(trials["t0001"]["attempts"], 1,
                         "original failure must not be replayed")
        self.assertEqual(trials["t0002"]["status"], "pass")

    def test_probe_command_clears_backoff_wait(self):
        self.rig.scenario = "quota_then_ok"
        m = self.rig.write_manifest(
            modes=("eager", "deferred"), models=("luna",), deadline=30,
            quota={"base_s": 60, "multiplier": 2, "cap_s": 3600,
                   "pause_above_s": 9999, "max_attempts_per_trial": 1,
                   "probe_timeout_s": 5, "probe_command": ["true"]})
        t0 = time.time()
        proc = self.rig.run_runner(["run", str(m)], env_extra=OK_ART)
        dt = time.time() - t0
        self.assertEqual(proc.returncode, 0)
        # a 60s backoff was cleared by the probe instead of slept
        self.assertLess(dt, 30, "probe should clear the wait, not sleep it")
        trials = self.state()["trials"]
        self.assertEqual([t["status"] for t in trials.values()],
                         ["provider_blocked", "pass"])
        self.assertEqual(trials["t0001"]["attempts"], 1)

    def test_pause_across_restart_preserves_terminal(self):
        self.rig.scenario = "quota"
        m = self.rig.write_manifest(
            modes=("eager", "deferred"), models=("luna",), deadline=30,
            quota={"base_s": 3600, "multiplier": 2, "cap_s": 3600,
                   "pause_above_s": 5, "max_attempts_per_trial": 1})
        proc = self.rig.run_runner(["run", str(m)], env_extra=OK_ART)
        self.assertEqual(proc.returncode, 3)
        state = self.state()
        self.assertEqual(state["trials"]["t0001"]["status"],
                         "provider_blocked")
        blocked_until = state["provider_backoff"]["fake"]["blocked_until"]
        self.assertGreater(blocked_until, time.time())
        # restart with the wait still in force: nothing runs, nothing changes
        self.rig.scenario = "ok"
        proc = self.rig.run_runner(["run", "--resume", str(m)],
                                   env_extra=OK_ART)
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(self.state()["trials"]["t0001"]["attempts"], 1)
        # quota resets: pending work proceeds on resume; original retained
        state = self.state()
        state["provider_backoff"]["fake"]["blocked_until"] = 0
        (self.rig.run_root / "test-campaign" / "campaign.json").write_text(
            json.dumps(state))
        self.rig.run_runner(["run", "--resume", str(m)], env_extra=OK_ART)
        trials = self.state()["trials"]
        self.assertEqual(trials["t0001"]["status"], "provider_blocked")
        self.assertEqual(trials["t0001"]["attempts"], 1)
        self.assertEqual(trials["t0002"]["status"], "pass")
        self.assertEqual(trials["t0002"]["attempts"], 1)

    def test_running_trial_marked_aborted_on_resume(self):
        self.rig.scenario = "ok"
        m = self.rig.write_manifest(modes=("eager",), models=("luna",),
                                    deadline=30)
        self.rig.run_runner(["run", str(m)], env_extra=OK_ART)
        # fabricate an interrupted run in a second campaign dir entry
        state = self.state()
        self.assertEqual(state["trials"]["t0001"]["status"], "pass")
        # simulate: a fresh campaign where t0001 was mid-flight at kill time
        m2 = self.rig.write_manifest(modes=("eager",), models=("luna",),
                                     deadline=30, campaign_id="crash-campaign")
        state2_path = self.rig.run_root / "crash-campaign" / "campaign.json"
        self.rig.run_runner(["run", str(m2)], env_extra=OK_ART)
        # hand-edit to running to emulate a killed runner mid-trial
        state2 = json.loads(state2_path.read_text())
        state2["trials"]["t0001"]["status"] = "running"
        state2_path.write_text(json.dumps(state2))
        proc = self.rig.run_runner(["run", "--resume", str(m2)],
                                   env_extra=OK_ART)
        self.assertEqual(proc.returncode, 0)
        t = json.loads(state2_path.read_text())["trials"]["t0001"]
        self.assertEqual(t["status"], "aborted")
        self.assertIn("not replayed", t["last_error"])
        self.assertEqual(t["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
