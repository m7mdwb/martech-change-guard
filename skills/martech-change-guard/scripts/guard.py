#!/usr/bin/env python3
"""Preflight and verify bulk CRM or marketing-data changes."""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

from engine import (GuardError, assess, diff_records, load_changeset, read_policy,
                    read_records, require_matching_schema, sha256_file, verify_changes,
                    write_plan, write_verification)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and verify deterministic plans for bulk CRM data changes.")
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="compare current and proposed exports")
    plan.add_argument("--before", required=True, help="current-state CSV/TSV/JSON/JSONL")
    plan.add_argument("--proposed", required=True, help="proposed-state export")
    plan.add_argument("--key", required=True, help="stable record ID field")
    plan.add_argument("--policy", help="optional JSON policy")
    plan.add_argument("--out", required=True, help="new or empty output directory")
    plan.add_argument("--canary-size", type=int, default=25)
    plan.add_argument("--force", action="store_true",
                      help="replace files in the named output directory")

    verify = commands.add_parser("verify", help="compare actual state with an approved plan")
    verify.add_argument("--before", required=True, help="same current-state export used to plan")
    verify.add_argument("--actual", required=True, help="fresh post-change export")
    verify.add_argument("--key", required=True, help="stable record ID field")
    verify.add_argument("--plan", required=True, help="plan artifact directory")
    verify.add_argument("--out", required=True, help="new or empty output directory")
    verify.add_argument("--force", action="store_true",
                        help="replace files in the named output directory")
    return parser


def render_plan(report, out_dir: str) -> str:
    blast = report["blast_radius"]
    lines = [
        "MarTech Change Guard - PLAN %s" % report["decision"].upper(),
        "=" * 72,
        "Risk: %s (%d/100)" % (report["risk"]["level"], report["risk"]["score"]),
        "Blast radius: %d of %d records (%.2f%%), %d field changes" %
        (blast["changed_records"], blast["before_records"], blast["changed_percent"],
         blast["field_changes"]),
        "Fields: %s" % (", ".join(blast["fields_changed"]) or "none"),
    ]
    if report["violations"]:
        lines.extend(["", "Violations:"])
        for item in report["violations"]:
            location = ""
            if item.get("record_id"):
                location = " [record %s, %s]" % (item["record_id"], item["field"])
            lines.append("- %s: %s%s" % (item["code"], item["message"], location))
    if report["review_reasons"]:
        lines.extend(["", "Review required:"])
        lines.extend("- %s" % reason for reason in report["review_reasons"])
    lines.extend(["", "Artifacts: %s" % os.path.abspath(out_dir)])
    return "\n".join(lines)


def render_verification(verification, out_dir: str) -> str:
    summary = verification["summary"]
    lines = [
        "MarTech Change Guard - VERIFY %s" % verification["status"].upper(),
        "=" * 72,
        "%d approved changes - %d mismatches - %d side effects - %d missing - %d unexpected records" %
        (summary["approved_field_changes"], summary["mismatches"],
         summary["side_effects"], summary["missing_records"], summary["unexpected_records"]),
        "Receipt: %s" % os.path.abspath(os.path.join(out_dir, "receipt.json")),
    ]
    return "\n".join(lines)


def run_plan(args) -> int:
    _, before = read_records(args.before, args.key)
    _, proposed = read_records(args.proposed, args.key)
    require_matching_schema(before, proposed, "before", "proposed")
    policy = read_policy(args.policy)
    changeset = diff_records(before, proposed, args.key)
    changeset["sources"] = {
        "before": {"name": os.path.basename(args.before), "sha256": sha256_file(args.before)},
        "proposed": {"name": os.path.basename(args.proposed),
                     "sha256": sha256_file(args.proposed)},
    }
    report = assess(changeset, policy)
    write_plan(args.out, changeset, report, args.canary_size, args.force)
    print(render_plan(report, args.out))
    return {"allow": 0, "review": 1, "block": 2}[report["decision"]]


def run_verify(args) -> int:
    _, before = read_records(args.before, args.key)
    _, actual = read_records(args.actual, args.key)
    require_matching_schema(before, actual, "before", "actual")
    changeset = load_changeset(args.plan)
    planned_before_hash = changeset.get("sources", {}).get("before", {}).get("sha256")
    if not planned_before_hash or sha256_file(args.before) != planned_before_hash:
        raise GuardError("--before does not match the current-state export used to create the plan")
    verification = verify_changes(changeset, before, actual, args.key)
    sources = {
        "before": {"name": os.path.basename(args.before), "sha256": sha256_file(args.before)},
        "actual": {"name": os.path.basename(args.actual), "sha256": sha256_file(args.actual)},
    }
    write_verification(args.out, args.plan, verification, sources, args.force)
    print(render_verification(verification, args.out))
    return 0 if verification["status"] == "passed" else 1


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return run_plan(args) if args.command == "plan" else run_verify(args)
    except GuardError as exc:
        print("guard error: %s" % exc, file=sys.stderr)
        return 3
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError) as exc:
        print("guard error: could not process the supplied files: %s" % exc, file=sys.stderr)
        return 3
    except Exception as exc:
        print("guard error: input could not be processed safely (%s). Check the export "
              "format or report this synthetic case." % type(exc).__name__, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
