"""Prove the MarTech Verify evidence -> guarded change -> receipt walkthrough."""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "martech-change-guard" / "scripts" / "guard.py"
FIXTURES = ROOT / "fixtures" / "connected"


def run_guard(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, errors="replace")


class ConnectedWorkflowTests(unittest.TestCase):
    def test_audit_evidence_plan_side_effect_and_clean_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            plan = root / "plan"
            evidence = FIXTURES / "routing-audit.json"
            result = run_guard(
                "plan", "--before", FIXTURES / "current-unrouted-leads.csv",
                "--proposed", FIXTURES / "proposed-routed-leads.csv", "--key", "lead_id",
                "--policy", FIXTURES / "routing-policy.json", "--evidence", evidence,
                "--reason", "Route nine leads identified as unassigned by MarTech Verify",
                "--out", plan,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            changeset = json.loads((plan / "changeset.json").read_text(encoding="utf-8"))
            self.assertEqual(changeset["summary"]["changed_records"], 9)
            self.assertEqual(changeset["sources"]["evidence"][0]["sha256"],
                             hashlib.sha256(evidence.read_bytes()).hexdigest())

            failed_dir = root / "failed"
            result = run_guard(
                "verify", "--before", FIXTURES / "current-unrouted-leads.csv", "--actual",
                FIXTURES / "actual-routed-side-effect.csv", "--key", "lead_id",
                "--plan", plan, "--out", failed_dir,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            failed = json.loads((failed_dir / "verification.json").read_text(encoding="utf-8"))
            self.assertEqual(failed["side_effects"][0]["field"], "consent_status")

            passed_dir = root / "passed"
            result = run_guard(
                "verify", "--before", FIXTURES / "current-unrouted-leads.csv", "--actual",
                FIXTURES / "actual-routed-safe.csv", "--key", "lead_id",
                "--plan", plan, "--out", passed_dir,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads((passed_dir / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "passed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
