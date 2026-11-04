"""Plan determinism and coverage tests (offline) [ours]."""
import unittest

from rig_common import Rig, runner


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.cleanup)

    def load(self, **kw):
        return runner.load_manifest(self.rig.write_manifest(**kw))

    def test_deterministic_order(self):
        a = runner.build_plan(self.load(seed=42))
        b = runner.build_plan(self.load(seed=42))
        self.assertEqual(a, b)

    def test_different_seed_reorders(self):
        plans = [tuple(s["trial_id"] + s["task"] + s["mode"]
                       for s in runner.build_plan(self.load(seed=n)))
                 for n in (1, 2, 3)]
        self.assertEqual(len(set(plans)), 3)

    def test_full_matrix_coverage(self):
        plan = runner.build_plan(self.load(
            modes=("eager", "deferred", "cli"), models=("luna", "glm"),
            seed=1))
        # 1 task x 3 modes x 2 models x 1 rep = 6 (cli counted once).
        self.assertEqual(len(plan), 6)
        combos = {(s["task"], s["mode"], s["model"]) for s in plan}
        self.assertEqual(len(combos), 6)
        self.assertEqual(len({s["trial_id"] for s in plan}), 6)

    def test_reps_expand(self):
        plan = runner.build_plan(self.load(modes=("eager",), models=("luna",),
                                           seed=1))
        self.assertEqual(len(plan), 1)
        m = self.load(modes=("eager",), models=("luna",), seed=1)
        m["matrix"]["reps"] = 2
        plan2 = runner.build_plan(m)
        self.assertEqual(len(plan2), 2)
        self.assertEqual(sorted(s["rep"] for s in plan2), [1, 2])

    def test_catalog_axis_for_all_modes(self):
        m = self.load(modes=("eager", "cli"), models=("luna",),
                      catalogs=["full", "required"], seed=1)
        plan = runner.build_plan(m)
        self.assertEqual(len(plan), 4)
        cli = [s for s in plan if s["mode"] == "cli"]
        self.assertEqual(len(cli), 2)
        self.assertEqual({s["catalog"] for s in cli}, {"required", "full"})

    def test_control_keeps_both_catalog_settings(self):
        m = self.load(modes=("eager",), models=("luna",),
                      catalogs=["full", "required"], task_catalog=[],
                      seed=1)
        plan = runner.build_plan(m)
        self.assertEqual(len(plan), 2)

    def test_cli_full_catalog_includes_unused_capability(self):
        m = self.load(modes=("cli",), catalogs=["required", "full"])
        m["capabilities"]["unused"] = {"skills": ["unused-skill"],
                                         "executables": ["unused-cli"],
                                         "env_names": ["UNUSED_CREDENTIAL"]}
        specs = {s["catalog"]: s for s in runner.build_plan(m)}
        self.assertEqual(runner.select_skills(m, specs["required"]), ["fake-gh"])
        self.assertEqual(runner.select_skills(m, specs["full"]),
                         ["fake-gh", "unused-skill"])
        self.assertIn("unused-cli", runner._required_executables(m, specs["full"]))

    def test_digest_stable_and_sensitive(self):
        m1 = self.load(seed=1)
        p1 = runner.build_plan(m1)
        d1 = runner.sha256_json({"manifest": m1, "plan": p1})
        d1b = runner.sha256_json({"manifest": m1, "plan": p1})
        self.assertEqual(d1, d1b)
        m2 = self.load(seed=2)
        d2 = runner.sha256_json({"manifest": m2,
                                 "plan": runner.build_plan(m2)})
        self.assertNotEqual(d1, d2)


if __name__ == "__main__":
    unittest.main()
