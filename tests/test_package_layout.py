"""Keep Codex and Claude packaging aligned and installable."""
from __future__ import annotations

import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION = "0.3.0"


class PackageTests(unittest.TestCase):
    def test_manifests_are_aligned(self):
        codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        claude = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        listing = next(item for item in market["plugins"]
                       if item["name"] == "martech-change-guard")
        self.assertEqual({codex["version"], claude["version"], listing["version"]}, {VERSION})
        self.assertEqual(codex["name"], "martech-change-guard")
        self.assertEqual(claude["name"], "martech-change-guard")
        self.assertEqual(codex["skills"], "./skills/")
        self.assertEqual(listing["source"], ".")
        self.assertIn("martech-verify", {item["name"] for item in market["plugins"]})

    def test_skill_metadata_is_user_ready(self):
        folder = ROOT / "skills/martech-change-guard"
        skill = (folder / "SKILL.md").read_text(encoding="utf-8")
        metadata = (folder / "agents/openai.yaml").read_text(encoding="utf-8")
        self.assertIn("name: martech-change-guard", skill)
        self.assertIn('display_name: "MarTech Change Guard"', metadata)
        self.assertIn("$martech-change-guard", metadata)
        self.assertNotRegex(skill + metadata, re.compile(r"\bTODO\b"))
        self.assertTrue((folder / "references/input-guide.md").is_file())

    def test_readme_has_current_install_paths_and_brand(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith("# MarTech Change Guard"))
        self.assertIn("claude plugin marketplace add m7mdwb/martech-change-guard", readme)
        self.assertIn("$skill-installer", readme)
        self.assertIn("MarTech safety loop", readme)
        self.assertNotRegex(readme, re.compile(r"\bMartech\b"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
