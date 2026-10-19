"""Check the public synthetic recipe, its evidence labels and overwrite boundary."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "examples/run_synthetic.py"


class PublicExamples(unittest.TestCase):
    def test_examples_and_repeatability_without_replacing_existing_output(self):
        with tempfile.TemporaryDirectory(prefix="android-helpers-examples-test-") as temporary:
            root = Path(temporary)
            outputs = [root / "first output", root / "second output"]
            for output in outputs:
                result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--output", str(output)],
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                summary = json.loads((output / "results.json").read_text())
                self.assertEqual(summary["evidence_kind"], "synthetic")
                self.assertEqual(len(summary["capture"]), 4)
                for mode, record in summary["capture"].items():
                    metadata = json.loads((output / "capture" / mode / record["metadata"]).read_text())
                    self.assertEqual(metadata["status"], "partial" if mode == "missing-notes" else "complete")
                    self.assertEqual(metadata["metadata"]["device_model"]["value"], "Simulated device")
                    self.assertFalse(Path(metadata["adb_command_prefix"][0]).exists())
                    if mode == "preserve":
                        self.assertNotIn("ui_dump", metadata["commands"])
                for outcome, code in (("observed", 0), ("verified_gap", 1), ("inconclusive", 2)):
                    data = json.loads((output / "network" / outcome / "result.json").read_text())
                    self.assertEqual(data["status"], outcome)
                    self.assertEqual(data["evidence_kind"], "synthetic")
                    self.assertEqual(summary["network"][outcome]["exit_code"], code)
            network_files = lambda path: {str(p.relative_to(path)): p.read_bytes()
                                          for p in (path / "network").rglob("*") if p.is_file()}
            self.assertEqual(network_files(outputs[0]), network_files(outputs[1]))
            digest = lambda: {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in outputs[0].rglob("*") if p.is_file()}
            before = digest()
            refused = subprocess.run([sys.executable, "-B", str(SCRIPT), "--output", str(outputs[0])],
                                     capture_output=True, text=True, timeout=10)
            self.assertEqual(refused.returncode, 2)
            self.assertEqual(before, digest())


if __name__ == "__main__":
    unittest.main()
