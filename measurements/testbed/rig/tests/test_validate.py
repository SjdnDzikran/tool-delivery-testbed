"""Manifest rejection tests (offline, no model spend) [ours]."""
import unittest
from pathlib import Path

from rig_common import Rig, runner

SMALL = dict(modes=("eager",), models=("luna",))


class TestValidateRejections(unittest.TestCase):
    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.cleanup)

    def write_and_validate(self, text: str):
        p = self.rig.root / "m.toml"
        p.write_text(text, encoding="utf-8")
        return runner.validate_manifest(runner.load_manifest(p))

    def test_valid_manifest_passes(self):
        errs = runner.validate_manifest(runner.load_manifest(
            self.rig.write_manifest(**SMALL)))
        self.assertEqual(errs, [])

    def test_placeholder_rejected(self):
        m = self.rig.manifest(**SMALL).replace(
            "args = [\"-c\", \"sleep 30\"]",
            "args = [\"-y\", \"pkg@PIN_VERSION\"]")
        p = self.rig.root / "m2.toml"
        p.write_text(m)
        with self.assertRaisesRegex(runner.ManifestError, "PIN_VERSION"):
            runner.load_manifest(p)

    def test_unknown_catalog_reference(self):
        m = self.rig.manifest(task_catalog=["srv", "ghost"], **SMALL)
        errs = self.write_and_validate(m)
        self.assertTrue(any("unknown catalog entry 'ghost'" in e for e in errs))

    def test_unknown_capability_reference(self):
        p = self.rig.write_manifest(**SMALL)
        text = p.read_text().replace('capabilities = ["gh"]',
                                     'capabilities = ["nope"]')
        p.write_text(text)
        errs = runner.validate_manifest(runner.load_manifest(p))
        self.assertTrue(any("unknown capability 'nope'" in e for e in errs))

    def test_missing_deadline(self):
        p = self.rig.write_manifest(**SMALL)
        text = "\n".join(l for l in p.read_text().splitlines()
                         if "deadline_s" not in l)
        p.write_text(text)
        errs = runner.validate_manifest(runner.load_manifest(p))
        self.assertTrue(any("deadline_s is required" in e for e in errs))

    def test_missing_verify(self):
        p = self.rig.write_manifest(**SMALL)
        text = "\n".join(l for l in p.read_text().splitlines()
                         if not l.startswith("verify ="))
        p.write_text(text)
        errs = runner.validate_manifest(runner.load_manifest(p))
        self.assertTrue(any("verify array is required" in e for e in errs))

    def test_unknown_mode(self):
        p = self.rig.write_manifest(modes=("eager", "wizard"), models=("luna",))
        errs = runner.validate_manifest(runner.load_manifest(p))
        self.assertTrue(any("unknown mode 'wizard'" in e for e in errs))

    def test_unknown_model_in_matrix(self):
        p = self.rig.write_manifest(modes=("eager",), models=("luna", "ghost"))
        errs = runner.validate_manifest(runner.load_manifest(p))
        self.assertTrue(any("unknown model 'ghost'" in e for e in errs))

    def test_exposure_not_settable_in_catalog(self):
        p = self.rig.write_manifest(**SMALL)
        text = p.read_text().replace(
            "[catalog.srv]", "[catalog.srv]\nexposure = \"direct\"")
        p.write_text(text)
        errs = runner.validate_manifest(runner.load_manifest(p))
        self.assertTrue(any("exposure is owned by the mode" in e for e in errs))

    def test_missing_model_provider(self):
        p = self.rig.write_manifest(**SMALL)
        text = "\n".join(l for l in p.read_text().splitlines()
                         if not l.startswith('provider = "fake"'))
        p.write_text(text)
        errs = runner.validate_manifest(runner.load_manifest(p))
        self.assertTrue(any("[models.luna] provider is required" in e
                            for e in errs))

    def test_wrong_schema_version(self):
        p = self.rig.root / "m.toml"
        p.write_text(self.rig.manifest(**SMALL).replace(
            "schema_version = 1", "schema_version = 99"))
        with self.assertRaisesRegex(runner.ManifestError, "schema_version"):
            runner.load_manifest(p)

    def test_task_without_catalog_is_valid_control(self):
        """A task with an empty catalog is a valid MCP-native control."""
        errs = runner.validate_manifest(runner.load_manifest(
            self.rig.write_manifest(task_catalog=[], **SMALL)))
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
