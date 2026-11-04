"""Offline verification tests: canary rig, observer plumbing, verifier
outcomes, manifest emission, poison fixture [ours — no model spend]."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

VER = Path(__file__).resolve().parents[1]
RIG = VER.parent
CANARY = VER / "canary"
TESTS_RIG = RIG / "tests"
sys.path.insert(0, str(RIG))
sys.path.insert(0, str(TESTS_RIG))


def py() -> str:
    return sys.executable


class CanaryMcpServerTest(unittest.TestCase):
    def handshake(self, variant: str, tool: str, args: dict,
                  marker: str) -> None:
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": tool, "arguments": args}},
        ]
        inp = "\n".join(json.dumps(x) for x in lines) + "\n"
        out = subprocess.run(
            [py(), str(CANARY / "mcp-canary-server.py"), "--server", variant],
            input=inp, capture_output=True, text=True, timeout=20)
        rs = [json.loads(l) for l in out.stdout.splitlines() if l.strip()]
        self.assertEqual(rs[0]["result"]["serverInfo"]["name"], variant)
        self.assertEqual(rs[1]["result"]["tools"][0]["name"], tool)
        self.assertEqual(rs[2]["result"]["content"][0]["text"], marker)

    def test_canary_variant(self):
        self.handshake("canary", "canary_echo", {"text": "ping"},
                       "CANARY_ECHO_OK: ping")

    def test_decoy_variant(self):
        self.handshake("decoy", "decoy_frobnicate", {},
                       "DECOY_FROBNICATE_OK: done")


class CanaryCliTest(unittest.TestCase):
    def test_echo_and_version(self):
        cli = str(CANARY / "canary-cli")
        self.assertEqual(
            subprocess.run([cli, "echo", "ping"], capture_output=True,
                           text=True).stdout, "CANARY_ECHO_OK: ping\n")
        p = subprocess.run([cli, "--version"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertIn("canary-cli", p.stdout)


class VerifyCanaryTest(unittest.TestCase):
    def run_verifier(self, content: str | None) -> int:
        with tempfile.TemporaryDirectory() as d:
            if content is not None:
                (Path(d) / "result.txt").write_text(content)
            return subprocess.run(
                [py(), str(VER / "verify_canary.py"), "--artifacts", d],
                capture_output=True, text=True).returncode

    def test_outcomes(self):
        self.assertEqual(self.run_verifier("CANARY_ECHO_OK: ping\n"), 0)
        self.assertEqual(self.run_verifier("CANARY_ECHO_OK: pong\n"), 1)
        self.assertEqual(self.run_verifier(""), 2)
        self.assertEqual(self.run_verifier(None), 3)


class ObserverPlumbingTest(unittest.TestCase):
    def test_wrapper_inserts_extension_before_dd(self):
        wrapper = VER / "observer" / "observed-pi-research.sh"
        env = dict(os.environ, PI_VERIFY_HARNESS="/bin/echo")
        p = subprocess.run([str(wrapper), "--mode", "json", "--no-extensions",
                            "SKILLTEXT", "--", "instruction-text"],
                           capture_output=True, text=True, env=env, timeout=30)
        argv = p.stdout.split()
        self.assertIn("-e", argv)
        obs = argv[argv.index("-e") + 1]
        self.assertTrue(obs.endswith("pi-request-observer.ts"))
        self.assertLess(argv.index("-e"), argv.index("--"))
        self.assertEqual(argv[-1], "instruction-text")

    def test_wrapper_refuses_without_dd(self):
        wrapper = VER / "observer" / "observed-pi-research.sh"
        env = dict(os.environ, PI_VERIFY_HARNESS="/bin/echo")
        p = subprocess.run([str(wrapper), "--mode", "json", "no separator"],
                           capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(p.returncode, 64)
        self.assertIn("refusing", p.stderr)

    def test_observer_module_loads_under_jiti(self):
        jiti = Path.home() / ".pi" / "research" / "node_modules" / "jiti" / \
            "lib" / "jiti.mjs"
        if not jiti.is_file():
            self.skipTest("jiti not available")
        code = (
            "import { createJiti } from '%s';\n"
            "const jiti = createJiti(import.meta.url);\n"
            "const m = await jiti.import('%s');\n"
            "if (typeof m.default !== 'function') throw new Error('bad');\n"
            "console.log('loaded');\n"
            % (jiti, VER / "observer" / "pi-request-observer.ts"))
        p = subprocess.run(["node", "--input-type=module", "-e", code],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("loaded", p.stdout)


class ManifestEmissionTest(unittest.TestCase):
    def test_every_suite_manifest_validates(self):
        sys.path.insert(0, str(VER))
        import live_matrix
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            for suite in ("probe", "required", "full-glm", "plain",
                          "controls", "poisoned"):
                path, meta = live_matrix.emit_manifest(suite, tmp)
                self.assertEqual(meta["trials_expected"] > 0, True, suite)
                import runner
                m = runner.load_manifest(path)
                errors = runner.validate_manifest(m)
                self.assertEqual(errors, [], f"{suite}: {errors}")

    def test_poison_fixture_contains_all_markers(self):
        sys.path.insert(0, str(VER))
        import live_matrix
        from analyze import POISON_MARKERS
        with tempfile.TemporaryDirectory() as d:
            pdir = live_matrix.build_poison(Path(d))
            blob = "\n".join(p.read_text(errors="replace")
                             for p in pdir.rglob("*") if p.is_file())
            for marker in POISON_MARKERS:
                self.assertIn(marker, blob)


class SkillIsolationTextTest(unittest.TestCase):
    """The rig skills dir must not contain the decoy; the verification
    skills dir must contain both canary and decoy."""

    def test_decoy_only_in_verification_skills(self):
        rig_skills = RIG / "skills"
        ver_skills = CANARY / "skills"
        self.assertFalse((rig_skills / "decoy-skill").exists())
        self.assertFalse((rig_skills / "canary-skill").exists())
        self.assertTrue((ver_skills / "canary-skill" / "SKILL.md").is_file())
        self.assertTrue((ver_skills / "decoy-skill" / "SKILL.md").is_file())


class AuxUsageDetectionTest(unittest.TestCase):
    """Runner counts assistant message_end usage only; session `usage`
    entries (cache_warm) and compaction usage are deterministic blind spots
    of the per-trial watchdog (GUIDE §6)."""

    def test_session_aux_usage_detected_offline(self):
        sys.path.insert(0, str(VER))
        import analyze
        with tempfile.TemporaryDirectory() as d:
            att = Path(d)
            (att / "sessions").mkdir()
            (att / "sessions" / "s.jsonl").write_text(
                json.dumps({"type": "message", "message": {
                    "role": "assistant",
                    "usage": {"totalTokens": 100}}}) + "\n" +
                json.dumps({"type": "usage", "kind": "cache_warm", "note": "a\u2028b\u2029c",
                            "usage": {"totalTokens": 5000}}, ensure_ascii=False) + "\n" +
                json.dumps({"type": "compaction",
                            "usage": {"totalTokens": 700}}) + "\n")
            aux = analyze.session_aux_usage(att)
            self.assertEqual(aux["aux_total_tokens"], 5700)
            self.assertEqual(aux["compaction_entries"], 1)
            ev = analyze.trial_usage(att / "nonexistent.jsonl")
            self.assertIn("error", ev)
            events = att / 'events.jsonl'
            events.write_text(json.dumps({'type': 'message_end', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'a\u2028b\u2029c'}], 'usage': {'totalTokens': 7}}}, ensure_ascii=False) + '\n')
            self.assertEqual(analyze.trial_usage(events)['runner_sum_total_tokens'], 7)


class PermissionsTest(unittest.TestCase):
    def test_no_group_or_world_writable_in_verification_tree(self):
        bad = []
        for p in VER.rglob("*"):
            if p.is_file():
                mode = p.stat().st_mode & 0o022
                if mode:
                    bad.append(str(p))
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
