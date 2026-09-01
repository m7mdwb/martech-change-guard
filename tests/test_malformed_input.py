"""Adversarial input and fail-closed behavior tests."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "martech-change-guard" / "scripts" / "guard.py"
FIXTURES = ROOT / "fixtures"


def run_guard(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, errors="replace")


class MalformedInputTests(unittest.TestCase):
    def test_broken_exports_never_traceback_and_fail_actionably(self):
        cases = {
            "empty.csv": b"",
            "header-only.csv": b"record_id,name\n",
            "ragged-short.csv": b"record_id,name\n1\n",
            "ragged-long.csv": b"record_id,name\n1,Ada,extra\n",
            "duplicate.csv": b"record_id,name,Name\n1,Ada,Lovelace\n",
            "empty-header.csv": b"record_id,,name\n1,x,Ada\n",
            "nul.csv": b"record_id,name\n1,Ada\x00Oops\n",
            "binary.csv": b"\x89PNG\r\n\x1a\n\x00\x00not-a-csv",
            "jpeg.csv": b"\xff\xd8\xff\xe0not-a-csv",
            "gif.csv": b"GIF89anot-a-csv",
            "pdf.csv": b"%PDF-1.7 not-a-csv",
            "xlsx.csv": b"PK\x03\x04not-a-csv",
            "bad-quote.csv": b'record_id,name\n1,"unterminated\n',
            "missing-key.csv": b"id,name\n1,Ada\n",
            "blank-key.csv": b"record_id,name\n,Ada\n",
            "duplicate-key.csv": b"record_id,name\n1,Ada\n1,Grace\n",
            "empty.json": b"",
            "empty-array.json": b"[]",
            "object.json": b'{"record_id":"1"}',
            "scalar.json": b"42",
            "row-scalar.json": b'[1,2]',
            "ragged.json": b'[{"record_id":"1","name":"Ada"},{"record_id":"2"}]',
            "duplicate-key.json": b'[{"record_id":"1","Name":"Ada","name":"Grace"}]',
            "nan.json": b'[{"record_id":"1","score":NaN}]',
            "truncated.jsonl": b'{"record_id":"1","name":"Ada"}\n{"record_id":',
            "bad-encoding.csv": b"\x81\x8d\x8f\x90\x9d",
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            for name, payload in cases.items():
                with self.subTest(name=name):
                    proposed = tmp_path / name
                    proposed.write_bytes(payload)
                    result = run_guard(
                        "plan", "--before", FIXTURES / "current.csv",
                        "--proposed", proposed, "--key", "record_id",
                        "--out", tmp_path / (name + "-out"),
                    )
                    self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
                    self.assertNotIn("Traceback", result.stdout + result.stderr)
                    self.assertTrue(result.stderr.strip(), name)

    def test_common_spreadsheet_exports_are_accepted(self):
        long_value = "x" * 200_000
        cases = {
            "bom.csv": "\ufeffrecord_id,name\n1,Ada\n",
            "crlf.csv": "record_id,name\r\n1,Ada\r\n",
            "no-final-newline.csv": "record_id,name\n1,Ada",
            "semicolon.csv": "record_id;name\n1;Ada\n",
            "tabs.tsv": "record_id\tname\n1\tAda\n",
            "huge.csv": "record_id,name\n1,%s\n" % long_value,
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            for name, content in cases.items():
                with self.subTest(name=name):
                    before = tmp_path / ("before-" + name)
                    proposed = tmp_path / ("proposed-" + name)
                    before.write_bytes(content.encode("utf-8"))
                    proposed.write_bytes(content.encode("utf-8"))
                    result = run_guard("plan", "--before", before, "--proposed", proposed,
                                       "--key", "record_id", "--out", tmp_path / (name + "-out"))
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_cp1252_export_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            payload = "record_id,name\r\n1,Andr\xe9\r\n".encode("cp1252")
            before = tmp_path / "before.csv"
            proposed = tmp_path / "proposed.csv"
            before.write_bytes(payload)
            proposed.write_bytes(payload)
            result = run_guard("plan", "--before", before, "--proposed", proposed,
                               "--key", "record_id", "--out", tmp_path / "out")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_column_is_not_interpreted_as_a_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            before = tmp_path / "before.csv"
            proposed = tmp_path / "proposed.csv"
            before.write_text("record_id,email,stage\n1,a@example.com,lead\n", encoding="utf-8")
            proposed.write_text("record_id,stage\n1,mql\n", encoding="utf-8")
            result = run_guard("plan", "--before", before, "--proposed", proposed,
                               "--key", "record_id", "--out", tmp_path / "out")
            self.assertEqual(result.returncode, 3)
            self.assertIn("schemas differ", result.stderr)
            self.assertFalse((tmp_path / "out").exists())

    def test_nonfinite_policy_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            policy = tmp_path / "policy.json"
            policy.write_text('{"hard_limit_percent": NaN}', encoding="utf-8")
            result = run_guard("plan", "--before", FIXTURES / "current.csv",
                               "--proposed", FIXTURES / "proposed-safe.csv",
                               "--key", "record_id", "--policy", policy,
                               "--out", tmp_path / "out")
            self.assertEqual(result.returncode, 3)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
