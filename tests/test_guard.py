"""Behavior tests for the plan and verification engine."""
from __future__ import annotations

import csv
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "martech-change-guard" / "scripts" / "guard.py"
FIXTURES = ROOT / "fixtures"
sys.path.insert(0, str(SCRIPT.parent))

from engine import GuardError, assess, diff_records, read_policy, select_canary  # noqa: E402


def run_guard(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


class EngineTests(unittest.TestCase):
    def test_diff_is_field_level_and_ignores_unchanged_records(self):
        before = {"1": {"id": "1", "stage": "lead", "owner": "ana"}}
        proposed = {"1": {"id": "1", "stage": "mql", "owner": "ana"}}
        result = diff_records(before, proposed, "id")
        self.assertEqual(result["summary"]["changed_records"], 1)
        self.assertEqual(result["changes"], [
            {"record_id": "1", "field": "stage", "before": "lead", "after": "mql"}
        ])

    def test_monotonic_regression_blocks(self):
        before = {"1": {"id": "1", "stage": "sql"}}
        proposed = {"1": {"id": "1", "stage": "mql"}}
        policy = read_policy(None)
        policy["monotonic_fields"] = {"stage": ["lead", "mql", "sql"]}
        report = assess(diff_records(before, proposed, "id"), policy)
        self.assertEqual(report["decision"], "block")
        self.assertIn("monotonic_regression", [v["code"] for v in report["violations"]])

    def test_fill_only_allows_fill_and_blocks_overwrite(self):
        policy = read_policy(None)
        policy["fill_only_fields"] = ["source"]
        allowed = assess(diff_records(
            {"1": {"id": "1", "source": ""}},
            {"1": {"id": "1", "source": "paid"}}, "id"), policy)
        self.assertFalse(allowed["violations"])
        blocked = assess(diff_records(
            {"1": {"id": "1", "source": "paid"}},
            {"1": {"id": "1", "source": "organic"}}, "id"), policy)
        self.assertIn("fill_only_overwrite", [v["code"] for v in blocked["violations"]])

    def test_record_addition_blocks(self):
        policy = read_policy(None)
        result = diff_records({"1": {"id": "1"}},
                              {"1": {"id": "1"}, "2": {"id": "2"}}, "id")
        report = assess(result, policy)
        self.assertEqual(report["decision"], "block")
        self.assertEqual(report["blast_radius"]["added_records"], 1)

    def test_canary_is_deterministic_and_diverse(self):
        changes = [
            {"record_id": "1", "field": "stage"},
            {"record_id": "2", "field": "stage"},
            {"record_id": "3", "field": "owner"},
            {"record_id": "4", "field": "source"},
        ]
        first = select_canary(changes, 3)
        self.assertEqual(first, select_canary(changes, 3))
        self.assertEqual(set(first), {"1" if "1" in first else "2", "3", "4"})

    def test_unknown_policy_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "policy.json"
            path.write_text('{"allow_everything": true}', encoding="utf-8")
            with self.assertRaises(GuardError):
                read_policy(str(path))


class CliTests(unittest.TestCase):
    def test_blocked_fixture_returns_two_and_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "plan"
            result = run_guard("plan", "--before", FIXTURES / "current.csv",
                               "--proposed", FIXTURES / "proposed-blocked.csv",
                               "--key", "record_id", "--policy", FIXTURES / "policy.json",
                               "--out", out)
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads((out / "risk-report.json").read_text(encoding="utf-8"))
            codes = {item["code"] for item in report["violations"]}
            self.assertIn("monotonic_regression", codes)
            self.assertIn("protected_field", codes)
            self.assertTrue((out / "rollback.csv").is_file())
            self.assertTrue((out / "manifest.json").is_file())

    def test_safe_fixture_reviews_then_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = pathlib.Path(tmp) / "plan"
            verification = pathlib.Path(tmp) / "verification"
            result = run_guard("plan", "--before", FIXTURES / "current.csv",
                               "--proposed", FIXTURES / "proposed-safe.csv",
                               "--key", "record_id", "--policy", FIXTURES / "policy.json",
                               "--out", plan)
            self.assertEqual(result.returncode, 1, result.stderr)
            result = run_guard("verify", "--before", FIXTURES / "current.csv",
                               "--actual", FIXTURES / "actual-safe.csv", "--key", "record_id",
                               "--plan", plan, "--out", verification)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads((verification / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "passed")
            self.assertEqual(len(receipt["plan"]["changeset_sha256"]), 64)

    def test_verification_detects_unapproved_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = pathlib.Path(tmp) / "plan"
            verification = pathlib.Path(tmp) / "verification"
            run_guard("plan", "--before", FIXTURES / "current.csv",
                      "--proposed", FIXTURES / "proposed-safe.csv", "--key", "record_id",
                      "--policy", FIXTURES / "policy.json", "--out", plan)
            result = run_guard("verify", "--before", FIXTURES / "current.csv",
                               "--actual", FIXTURES / "actual-side-effect.csv",
                               "--key", "record_id", "--plan", plan, "--out", verification)
            self.assertEqual(result.returncode, 1, result.stderr)
            evidence = json.loads((verification / "verification.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["status"], "failed")
            self.assertEqual(evidence["side_effects"][0]["field"], "note")

    def test_verification_rejects_tampered_changeset(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = pathlib.Path(tmp) / "plan"
            verification = pathlib.Path(tmp) / "verification"
            run_guard("plan", "--before", FIXTURES / "current.csv",
                      "--proposed", FIXTURES / "proposed-safe.csv", "--key", "record_id",
                      "--policy", FIXTURES / "policy.json", "--out", plan)
            path = plan / "changeset.json"
            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["changes"][0]["after"] = "customer"
            path.write_text(json.dumps(changed), encoding="utf-8")
            result = run_guard("verify", "--before", FIXTURES / "current.csv",
                               "--actual", FIXTURES / "actual-safe.csv", "--key", "record_id",
                               "--plan", plan, "--out", verification)
            self.assertEqual(result.returncode, 3)
            self.assertIn("does not match the plan manifest", result.stderr)

    def test_nonempty_output_refuses_without_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "plan"
            out.mkdir()
            (out / "keep.txt").write_text("do not overwrite", encoding="utf-8")
            result = run_guard("plan", "--before", FIXTURES / "current.csv",
                               "--proposed", FIXTURES / "proposed-safe.csv",
                               "--key", "record_id", "--out", out)
            self.assertEqual(result.returncode, 3)
            self.assertEqual((out / "keep.txt").read_text(encoding="utf-8"), "do not overwrite")

    def test_rollback_contains_inverse_and_concurrency_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "plan"
            run_guard("plan", "--before", FIXTURES / "current.csv",
                      "--proposed", FIXTURES / "proposed-safe.csv", "--key", "record_id",
                      "--policy", FIXTURES / "policy.json", "--out", out)
            with open(out / "rollback.csv", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            stage = next(row for row in rows if row["record_id"] == "1" and row["field"] == "lifecycle_stage")
            self.assertEqual(json.loads(stage["value_json"]), "lead")
            self.assertEqual(json.loads(stage["expected_current_value_json"]), "mql")


if __name__ == "__main__":
    unittest.main(verbosity=2)
