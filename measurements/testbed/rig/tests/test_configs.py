"""Exact per-arm configuration generation tests (offline) [ours].

Verifies the generated agent dir and pi argv for every mode: MCP exposure,
explicit skill loading, --no-mcp for the CLI arm, and that non-selected
skills (the ponytail decoy) never appear anywhere.
"""
import json
import unittest
from pathlib import Path

from rig_common import Rig, runner


class TestArmConfigs(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.cleanup)
        self.m = runner.load_manifest(self.rig.write_manifest(
            modes=("eager", "deferred", "cli"), models=("luna",)))
        self.specs = runner.build_plan(self.m)

    def prep(self, mode):
        spec = next(s for s in self.specs if s["mode"] == mode)
        tdir = self.rig.root / f"tdir-{mode}"
        tdir.mkdir(mode=0o700)
        info = runner.prepare_agent_dir(self.m, spec, {"attempts": 0}, tdir)
        argv = runner.build_argv(
            self.m, spec, "PROMPT", info["agent_dir"], tdir / "sessions")
        return info, argv

    def flags(self, argv):
        return argv[1:-2]  # drop binary and ["--", "PROMPT"]

    def test_eager_config(self):
        info, argv = self.prep("eager")
        mcp = json.loads((info["agent_dir"] / "mcp.json").read_text())
        self.assertEqual(mcp["mcpServers"]["srv"]["exposure"], "direct")
        f = self.flags(argv)
        self.assertIn("-e", f)
        self.assertEqual(f[f.index("-e") + 1], "builtin:mcp")
        self.assertNotIn("--no-mcp", f)
        self.assertNotIn("--skill", f)
        self.assertNotIn("builtin:tool-search", f)

    def test_deferred_config(self):
        info, argv = self.prep("deferred")
        mcp = json.loads((info["agent_dir"] / "mcp.json").read_text())
        self.assertEqual(mcp["mcpServers"]["srv"]["exposure"], "deferred")
        f = self.flags(argv)
        exts = [f[i + 1] for i, v in enumerate(f) if v == "-e"]
        self.assertEqual(exts, ["builtin:mcp", "builtin:tool-search"],
                         "deferred needs tool_search or deferred tools are "
                         "unreachable")
        self.assertNotIn("--no-mcp", f)

    def test_eager_deferred_identical_except_exposure(self):
        e = json.loads((self.prep("eager")[0]["agent_dir"] / "mcp.json")
                       .read_text())
        d = json.loads((self.prep("deferred")[0]["agent_dir"] / "mcp.json")
                       .read_text())
        for name in e["mcpServers"]:
            ee = dict(e["mcpServers"][name]); ee.pop("exposure")
            de = dict(d["mcpServers"][name]); de.pop("exposure")
            self.assertEqual(ee, de)

    def test_cli_config(self):
        info, argv = self.prep("cli")
        self.assertFalse((info["agent_dir"] / "mcp.json").exists(),
                         "cli arm must have no mcp.json")
        f = self.flags(argv)
        self.assertIn("--no-mcp", f)
        self.assertIn("--no-skills", f)
        self.assertNotIn("-e", f)
        skills = [f[i + 1] for i, v in enumerate(f) if v == "--skill"]
        self.assertEqual(len(skills), 1)
        self.assertTrue(skills[0].startswith(str(info["agent_dir"] / "skills")))
        self.assertEqual(Path(skills[0]).name, "fake-gh")

    def test_common_flags_all_modes(self):
        for mode in ("eager", "deferred", "cli"):
            _, argv = self.prep(mode)
            f = self.flags(argv)
            for flag in ("--mode", "--no-extensions", "--no-context-files",
                         "--no-prompt-templates", "--no-themes",
                         "--no-approve", "--session-dir", "--no-skills",
                         "--provider", "--model", "--thinking"):
                self.assertIn(flag, f, f"{mode} missing {flag}")
            self.assertEqual(f[f.index("--provider") + 1], "fake")
            self.assertEqual(f[f.index("--model") + 1], "fake-model-1")
            self.assertEqual(f[f.index("--thinking") + 1], "medium")

    def test_ponytail_decoy_never_selected(self):
        for mode in ("eager", "deferred", "cli"):
            info, argv = self.prep(mode)
            self.assertNotIn("ponytail", info["skills"])
            self.assertFalse(any("ponytail" in a for a in argv))
            agent_skills = list((info["agent_dir"] / "skills").glob("*")) \
                if (info["agent_dir"] / "skills").exists() else []
            self.assertNotIn("ponytail", [p.name for p in agent_skills])

    def test_mcp_arms_have_no_skill_flags_or_dirs(self):
        for mode in ("eager", "deferred"):
            info, argv = self.prep(mode)
            self.assertEqual(info["skills"], [])
            self.assertNotIn("--skill", self.flags(argv))
            self.assertFalse((info["agent_dir"] / "skills").exists())

    def test_settings_pin_model(self):
        for mode in ("eager", "deferred", "cli"):
            info, _ = self.prep(mode)
            s = json.loads((info["agent_dir"] / "settings.json").read_text())
            self.assertEqual(s, {
                "defaultProvider": "fake",
                "defaultModel": "fake-model-1",
                "defaultThinkingLevel": "medium",
            })

    def test_auth_symlink_private(self):
        import os
        import stat
        info, _ = self.prep("eager")
        auth = info["agent_dir"] / "auth.json"
        self.assertTrue(auth.is_symlink())
        self.assertEqual(os.path.realpath(auth),
                         str(self.rig.auth.resolve()))
        self.assertEqual(
            stat.S_IMODE(info["agent_dir"].stat().st_mode) & 0o077, 0,
            "agent dir must be private (0700)")

    def test_auth_copy_mode(self):
        m = runner.load_manifest(self.rig.write_manifest(
            modes=("eager",), models=("luna",)))
        m["harness"]["auth_mode"] = "copy"
        spec = runner.build_plan(m)[0]
        tdir = self.rig.root / "tdir-copy"
        tdir.mkdir(mode=0o700)
        info = runner.prepare_agent_dir(m, spec, {"attempts": 0}, tdir)
        auth = info["agent_dir"] / "auth.json"
        self.assertTrue(auth.is_file() and not auth.is_symlink())
        import stat
        self.assertEqual(stat.S_IMODE(auth.stat().st_mode) & 0o077, 0)

    def test_required_catalog_narrows(self):
        m = runner.load_manifest(self.rig.write_manifest(
            modes=("eager",), models=("luna",), catalogs=["full", "required"],
            task_catalog=[], seed=1))
        # Controls retain both settings, even when the smaller catalog is empty.
        self.assertEqual(len(runner.build_plan(m)), 2)
        m2 = runner.load_manifest(self.rig.write_manifest(
            modes=("eager",), models=("luna",), catalogs=["full", "required"],
            task_catalog=["srv"], seed=1))
        plan = runner.build_plan(m2)
        self.assertEqual(len(plan), 2)
        full = next(s for s in plan if s["catalog"] == "full")
        req = next(s for s in plan if s["catalog"] == "required")
        self.assertEqual(runner.select_catalog(m2, full), ["srv"])
        self.assertEqual(runner.select_catalog(m2, req), ["srv"])
        # and narrowing actually bites when the catalog has >1 entry:
        m2["catalog"]["other"] = {"command": "sh", "args": ["-c", "x"],
                                    "timeout": 1}
        self.assertEqual(runner.select_catalog(m2, full), ["other", "srv"])
        self.assertEqual(runner.select_catalog(m2, req), ["srv"])


if __name__ == "__main__":
    unittest.main()
