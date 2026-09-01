"""Deterministic planning and verification engine for MarTech Change Guard."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_POLICY = {
    "allowed_fields": [],
    "protected_fields": [],
    "immutable_fields": [],
    "fill_only_fields": [],
    "monotonic_fields": {},
    "approval_required_over_records": 100,
    "approval_required_over_percent": 10.0,
    "hard_limit_records": 10000,
    "hard_limit_percent": 100.0,
    "risk_weights": {},
}

BUILTIN_FIELD_WEIGHTS = {
    "email": 20,
    "phone": 15,
    "consent": 25,
    "opted_out": 30,
    "unsubscribe": 30,
    "owner": 15,
    "lifecycle": 12,
    "stage": 12,
    "amount": 10,
    "revenue": 10,
}


class GuardError(ValueError):
    """A user-correctable input, policy, or artifact error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scalar(value: Any) -> Any:
    """Keep JSON scalar types, stringify compound values deterministically."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return stable_json(value)


def is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def comparable(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().casefold()


def values_equal(left: Any, right: Any) -> bool:
    # Exports disagree about scalar types: JSON false and CSV "false" should not create
    # a phantom CRM change. Compound values were already stringified by the loaders.
    return comparable(scalar(left)) == comparable(scalar(right))


def _raise_field_limit() -> None:
    """csv refuses fields over 131,072 characters and raises rather than truncating.

    One long URL or base64 blob in a single cell is enough, and "field larger than field
    limit" is not a sentence anyone can act on. Ported from martech-verify, where this was
    a real crash rather than a hypothetical one.
    """
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


_raise_field_limit()

_MAGIC = (
    (bytes([0x89]) + b"PNG", "PNG image"),
    (bytes([0xFF, 0xD8, 0xFF]), "JPEG image"),
    (b"GIF87a", "GIF image"),
    (b"GIF89a", "GIF image"),
    (b"%PDF-", "PDF document"),
    (b"PK" + bytes([0x03, 0x04]), "ZIP or XLSX file"),
)


def _decode_bytes(raw: bytes) -> str:
    """Excel saves cp1252 and exports arrive with a BOM. Never raise on encoding."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_text(path: str) -> str:
    """Read a text export, refusing bytes that cannot support a trustworthy comparison.

    Ported from martech-verify. A renamed PNG used to decode as latin-1 and yield a
    confident empty changeset, and for a tool that authorises writes to a CRM that is
    considerably worse than crashing. Fail closed instead.
    """
    with open(path, "rb") as handle:
        raw = handle.read()
    if not raw.strip():
        raise GuardError("%s contains no data. Export at least one row and try again." % path)
    for signature, kind in _MAGIC:
        if raw.startswith(signature):
            raise GuardError("%s is a %s, not a text export. Export CSV, TSV or JSON Lines."
                             % (path, kind))
    if bytes([0x00]) in raw:
        raise GuardError("%s contains NUL bytes and appears binary or UTF-16. Export it as "
                         "UTF-8 CSV, TSV or JSON Lines." % path)
    controls = sum(byte < 32 and byte not in (9, 10, 13) for byte in raw[:65536])
    if controls > max(4, len(raw[:65536]) // 100):
        raise GuardError("%s contains binary control bytes. Export a plain-text CSV, TSV or "
                         "JSON Lines file." % path)
    return _decode_bytes(raw)



def _json_constant(value: str) -> None:
    raise GuardError("JSON contains non-finite number %s; use a finite number or null" % value)


def _json_object(pairs) -> Dict[str, Any]:
    result = {}
    folded = set()
    for key, value in pairs:
        normalized = str(key).casefold()
        if normalized in folded:
            raise GuardError("JSON object contains duplicate field %r" % key)
        folded.add(normalized)
        result[key] = value
    return result


def _loads_json(text: str) -> Any:
    return json.loads(text, parse_constant=_json_constant, object_pairs_hook=_json_object)


def _read_delimited(path: str) -> List[Dict[str, Any]]:
    text = _read_text(path)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if path.lower().endswith(".tsv") else csv.excel
    try:
        reader = csv.reader(io.StringIO(text, newline=""), dialect=dialect, strict=True)
        raw_header = next(reader, None)
        if not raw_header:
            raise GuardError("input has no header row: %s" % path)
        header = [str(name).strip() for name in raw_header]
        if any(not name for name in header):
            raise GuardError("input has an empty column name: %s" % path)
        folded = [name.casefold() for name in header]
        duplicates = sorted({name for name in folded if folded.count(name) > 1})
        if duplicates:
            raise GuardError("input has duplicate column names: %s" % ", ".join(duplicates))
        rows = []
        for number, values in enumerate(reader, 2):
            if not values or not any(values):
                continue
            if len(values) != len(header):
                raise GuardError("row %d has %d fields but the header has %d: %s" %
                                 (number, len(values), len(header), path))
            rows.append({header[index]: scalar(value) for index, value in enumerate(values)})
    except csv.Error as exc:
        raise GuardError("could not parse delimited input %s: %s" % (path, exc))
    if not rows:
        raise GuardError("input has a header but no data rows: %s" % path)
    return rows


def _read_json(path: str) -> List[Dict[str, Any]]:
    text = _read_text(path)
    try:
        parsed = _loads_json(text)
    except json.JSONDecodeError:
        parsed = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                parsed.append(_loads_json(line))
            except json.JSONDecodeError as exc:
                raise GuardError("invalid JSON on line %d of %s: %s" %
                                 (number, path, exc.msg))
    if isinstance(parsed, dict):
        parsed = parsed.get("records")
    if not isinstance(parsed, list):
        raise GuardError("JSON input must be an array, JSON Lines, or {'records': [...]}")
    if any(not isinstance(row, dict) for row in parsed):
        raise GuardError("every input record must be a JSON object")
    if not parsed:
        raise GuardError("JSON input contains no records: %s" % path)
    rows = [{str(k).strip(): scalar(v) for k, v in row.items()} for row in parsed]
    expected_fields = set(rows[0])
    for number, row in enumerate(rows, 1):
        folded = [name.casefold() for name in row]
        if any(not name for name in row) or len(set(folded)) != len(folded):
            raise GuardError("JSON record %d has empty or duplicate field names" % number)
        if set(row) != expected_fields:
            raise GuardError("JSON record %d has different fields. Export a rectangular "
                             "record set with the same fields on every record." % number)
    return rows


def read_records(path: str, key: str) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    if not os.path.isfile(path):
        raise GuardError("input file does not exist: %s" % path)
    lower = path.lower()
    rows = _read_json(path) if lower.endswith((".json", ".jsonl", ".ndjson")) \
        else _read_delimited(path)
    indexed: Dict[str, Dict[str, Any]] = {}
    for number, row in enumerate(rows, 2):
        if key not in row or is_empty(row.get(key)):
            raise GuardError("missing '%s' on input row %d of %s" % (key, number, path))
        record_id = str(row[key]).strip()
        if record_id in indexed:
            raise GuardError("duplicate '%s' value %r in %s" % (key, record_id, path))
        indexed[record_id] = row
    return rows, indexed


def record_schema(records: Dict[str, Dict[str, Any]]) -> set:
    fields = set()
    for row in records.values():
        fields.update(row)
    return fields


def require_matching_schema(left: Dict[str, Dict[str, Any]], right: Dict[str, Dict[str, Any]],
                            left_name: str, right_name: str) -> None:
    left_fields, right_fields = record_schema(left), record_schema(right)
    if left_fields == right_fields:
        return
    missing = sorted(left_fields - right_fields)
    extra = sorted(right_fields - left_fields)
    details = []
    if missing:
        details.append("missing from %s: %s" % (right_name, ", ".join(missing)))
    if extra:
        details.append("only in %s: %s" % (right_name, ", ".join(extra)))
    raise GuardError("export schemas differ (%s). Export the same columns in both files; "
                     "a missing column is never treated as permission to clear data." % "; ".join(details))


def read_policy(path: Optional[str]) -> Dict[str, Any]:
    supplied: Dict[str, Any] = {}
    if path:
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                supplied = json.load(handle, parse_constant=_json_constant,
                                     object_pairs_hook=_json_object)
        except (OSError, json.JSONDecodeError) as exc:
            raise GuardError("could not read policy %s: %s" % (path, exc))
        if not isinstance(supplied, dict):
            raise GuardError("policy must be a JSON object")
    unknown = sorted(set(supplied) - set(DEFAULT_POLICY))
    if unknown:
        raise GuardError("unknown policy fields: %s" % ", ".join(unknown))
    policy = dict(DEFAULT_POLICY)
    policy.update(supplied)
    for name in ("allowed_fields", "protected_fields", "immutable_fields", "fill_only_fields"):
        if not isinstance(policy[name], list) or any(not isinstance(v, str) for v in policy[name]):
            raise GuardError("policy.%s must be an array of field names" % name)
    if not isinstance(policy["monotonic_fields"], dict):
        raise GuardError("policy.monotonic_fields must be an object")
    for field, order in policy["monotonic_fields"].items():
        if not isinstance(order, list) or len(order) < 2:
            raise GuardError("monotonic order for %s must contain at least two values" % field)
        folded = [comparable(v) for v in order]
        if len(set(folded)) != len(folded):
            raise GuardError("monotonic order for %s contains duplicate values" % field)
    if not isinstance(policy["risk_weights"], dict):
        raise GuardError("policy.risk_weights must be an object")
    for field, weight in policy["risk_weights"].items():
        if (not isinstance(weight, (int, float)) or isinstance(weight, bool) or
                (isinstance(weight, float) and not math.isfinite(weight)) or
                not 0 <= weight <= 50):
            raise GuardError("risk weight for %s must be a number from 0 to 50" % field)
    for name in ("approval_required_over_records", "approval_required_over_percent",
                 "hard_limit_records", "hard_limit_percent"):
        value = policy[name]
        if (not isinstance(value, (int, float)) or isinstance(value, bool) or
                (isinstance(value, float) and not math.isfinite(value)) or value < 0):
            raise GuardError("policy.%s must be a non-negative number" % name)
    for name in ("approval_required_over_percent", "hard_limit_percent"):
        if policy[name] > 100:
            raise GuardError("policy.%s must be between 0 and 100" % name)
    return policy


def diff_records(before: Dict[str, Dict[str, Any]], proposed: Dict[str, Dict[str, Any]],
                 key: str) -> Dict[str, Any]:
    before_ids, proposed_ids = set(before), set(proposed)
    added_ids = sorted(proposed_ids - before_ids)
    removed_ids = sorted(before_ids - proposed_ids)
    changes = []
    changed_ids = set()
    fields_changed = set()
    for record_id in sorted(before_ids & proposed_ids):
        left, right = before[record_id], proposed[record_id]
        for field in sorted((set(left) | set(right)) - {key}):
            old, new = left.get(field), right.get(field)
            if not values_equal(old, new):
                changes.append({"record_id": record_id, "field": field,
                                "before": scalar(old), "after": scalar(new)})
                changed_ids.add(record_id)
                fields_changed.add(field)
    return {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "key": key,
        "summary": {
            "before_records": len(before),
            "proposed_records": len(proposed),
            "changed_records": len(changed_ids),
            "field_changes": len(changes),
            "fields_changed": sorted(fields_changed),
            "added_records": len(added_ids),
            "removed_records": len(removed_ids),
        },
        "added_ids": added_ids,
        "removed_ids": removed_ids,
        "changes": changes,
    }


def _violation(code: str, message: str, severity: str = "high",
               change: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {"code": code, "severity": severity, "message": message}
    if change:
        out.update({"record_id": change["record_id"], "field": change["field"]})
    return out


def _field_weight(field: str, policy: Dict[str, Any]) -> int:
    if field in policy["risk_weights"]:
        return int(policy["risk_weights"][field])
    folded = field.casefold()
    return max([weight for needle, weight in BUILTIN_FIELD_WEIGHTS.items() if needle in folded]
               or [0])


def assess(changeset: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    summary = changeset["summary"]
    before_count = max(summary["before_records"], 1)
    changed_count = summary["changed_records"]
    changed_percent = round(changed_count / before_count * 100, 2)
    violations: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if changeset["added_ids"]:
        violations.append(_violation(
            "record_additions_unsupported",
            "%d record additions are present; V1 plans updates only" % len(changeset["added_ids"]),
            "critical"))
    if changeset["removed_ids"]:
        violations.append(_violation(
            "record_deletions_unsupported",
            "%d record deletions are present; V1 plans updates only" % len(changeset["removed_ids"]),
            "critical"))

    allowed = set(policy["allowed_fields"])
    protected = set(policy["protected_fields"])
    immutable = set(policy["immutable_fields"])
    fill_only = set(policy["fill_only_fields"])
    monotonic = policy["monotonic_fields"]

    for change in changeset["changes"]:
        field = change["field"]
        if allowed and field not in allowed:
            violations.append(_violation("field_not_allowed", "%s is outside allowed_fields" % field,
                                         "high", change))
        if field in protected:
            violations.append(_violation("protected_field", "%s is protected" % field,
                                         "critical", change))
        if field in immutable:
            violations.append(_violation("immutable_field", "%s is immutable" % field,
                                         "critical", change))
        if field in fill_only and (not is_empty(change["before"]) or is_empty(change["after"])):
            violations.append(_violation(
                "fill_only_overwrite", "%s may only change from empty to populated" % field,
                "high", change))
        if field in monotonic:
            order = [comparable(v) for v in monotonic[field]]
            old, new = comparable(change["before"]), comparable(change["after"])
            if old not in order or new not in order:
                violations.append(_violation(
                    "unknown_monotonic_value", "%s contains a value outside its configured order" % field,
                    "high", change))
            elif order.index(new) < order.index(old):
                violations.append(_violation(
                    "monotonic_regression", "%s moves backward from %r to %r" %
                    (field, change["before"], change["after"]), "critical", change))

    if changed_count > policy["hard_limit_records"]:
        violations.append(_violation(
            "record_hard_limit", "%d changed records exceed the hard limit of %s" %
            (changed_count, policy["hard_limit_records"]), "critical"))
    if changed_percent > policy["hard_limit_percent"]:
        violations.append(_violation(
            "percent_hard_limit", "%.2f%% blast radius exceeds the hard limit of %s%%" %
            (changed_percent, policy["hard_limit_percent"]), "critical"))

    review_reasons = []
    if changed_count > policy["approval_required_over_records"]:
        review_reasons.append("changed records exceed the approval threshold")
    if changed_percent > policy["approval_required_over_percent"]:
        review_reasons.append("changed percentage exceeds the approval threshold")
    if changed_count == 0 and not changeset["added_ids"] and not changeset["removed_ids"]:
        warnings.append({"code": "no_changes", "message": "the proposed export has no changes"})

    score = min(25, int(changed_percent / 4))
    if changed_count > 100:
        score += 10
    if changed_count > 1000:
        score += 10
    distinct_fields = set(change["field"] for change in changeset["changes"])
    score += sum(_field_weight(field, policy) for field in distinct_fields)
    if changeset["added_ids"]:
        score += 30
    if changeset["removed_ids"]:
        score += 50
    score += 50 if any(v["severity"] == "critical" for v in violations) else 0
    score += 25 if violations and not any(v["severity"] == "critical" for v in violations) else 0
    score = min(100, score)
    level = "low" if score < 25 else "medium" if score < 50 else "high" if score < 75 else "critical"
    decision = "block" if violations else "review" if review_reasons or score >= 25 else "allow"

    return {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "decision": decision,
        "risk": {"score": score, "level": level,
                 "note": "Deterministic heuristic, not a calibrated probability."},
        "blast_radius": {
            "changed_records": changed_count,
            "before_records": summary["before_records"],
            "changed_percent": changed_percent,
            "field_changes": summary["field_changes"],
            "fields_changed": summary["fields_changed"],
            "added_records": summary["added_records"],
            "removed_records": summary["removed_records"],
        },
        "review_reasons": review_reasons,
        "violations": violations,
        "warnings": warnings,
    }


def select_canary(changes: Sequence[Dict[str, Any]], size: int) -> List[str]:
    if size <= 0:
        return []
    by_record: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for change in changes:
        by_record[change["record_id"]].append(change)
    groups: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
    for record_id, record_changes in by_record.items():
        signature = tuple(sorted(change["field"] for change in record_changes))
        groups[signature].append(record_id)
    queues = []
    for signature in sorted(groups):
        ordered = sorted(groups[signature], key=lambda rid: sha256_bytes(rid.encode("utf-8")))
        queues.append(deque(ordered))
    selected = []
    while queues and len(selected) < min(size, len(by_record)):
        remaining = []
        for queue in queues:
            if queue and len(selected) < size:
                selected.append(queue.popleft())
            if queue:
                remaining.append(queue)
        queues = remaining
    return selected


def _write_json(path: str, value: Any) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _write_operations(path: str, changes: Iterable[Dict[str, Any]], reverse: bool = False) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["record_id_json", "field_json", "value_json",
                                                    "expected_current_value_json"])
        writer.writeheader()
        for change in changes:
            writer.writerow({
                "record_id_json": _json_cell(change["record_id"]),
                "field_json": _json_cell(change["field"]),
                "value_json": _json_cell(change["before"] if reverse else change["after"]),
                "expected_current_value_json": _json_cell(
                    change["after"] if reverse else change["before"]),
            })


def prepare_output(path: str, force: bool = False) -> None:
    if os.path.exists(path):
        if not os.path.isdir(path):
            raise GuardError("output path exists and is not a directory: %s" % path)
        if os.listdir(path) and not force:
            raise GuardError("output directory is not empty; choose another path or explicitly use --force")
    else:
        os.makedirs(path)


def write_plan(out_dir: str, changeset: Dict[str, Any], report: Dict[str, Any],
               canary_size: int, force: bool = False) -> Dict[str, str]:
    prepare_output(out_dir, force)
    changeset_path = os.path.join(out_dir, "changeset.json")
    risk_path = os.path.join(out_dir, "risk-report.json")
    canary_path = os.path.join(out_dir, "canary.csv")
    rollback_path = os.path.join(out_dir, "rollback.csv")
    _write_json(changeset_path, changeset)
    _write_json(risk_path, report)
    selected = set(select_canary(changeset["changes"], canary_size))
    _write_operations(canary_path,
                      [c for c in changeset["changes"] if c["record_id"] in selected])
    _write_operations(rollback_path, changeset["changes"], reverse=True)
    hashes = {name: sha256_file(os.path.join(out_dir, name)) for name in
              ("changeset.json", "risk-report.json", "canary.csv", "rollback.csv")}
    manifest = {"schema_version": "1.0", "created_at": utc_now(), "sha256": hashes}
    manifest_path = os.path.join(out_dir, "manifest.json")
    _write_json(manifest_path, manifest)
    hashes["manifest.json"] = sha256_file(manifest_path)
    return hashes


def load_changeset(plan_dir: str) -> Dict[str, Any]:
    path = os.path.join(plan_dir, "changeset.json")
    manifest_path = os.path.join(plan_dir, "manifest.json")
    try:
        with open(manifest_path, "r", encoding="utf-8-sig") as handle:
            manifest = json.load(handle)
        with open(path, "r", encoding="utf-8-sig") as handle:
            changeset = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise GuardError("could not read plan artifacts: %s" % exc)
    expected_hashes = manifest.get("sha256", {})
    required = ("changeset.json", "risk-report.json", "canary.csv", "rollback.csv")
    for name in required:
        artifact = os.path.join(plan_dir, name)
        expected_hash = expected_hashes.get(name)
        if not expected_hash or not os.path.isfile(artifact) or sha256_file(artifact) != expected_hash:
            raise GuardError("%s does not match the plan manifest; do not verify a modified plan" % name)
    if changeset.get("schema_version") != "1.0" or not isinstance(changeset.get("changes"), list):
        raise GuardError("unsupported or malformed changeset")
    return changeset


def verify_changes(changeset: Dict[str, Any], before: Dict[str, Dict[str, Any]],
                   actual: Dict[str, Dict[str, Any]], key: str) -> Dict[str, Any]:
    if changeset.get("key") != key:
        raise GuardError("verification key does not match the plan key")
    approved: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for change in changeset["changes"]:
        approved[change["record_id"]][change["field"]] = change["after"]
    mismatches, side_effects = [], []
    missing_records = sorted(set(before) - set(actual))
    unexpected_records = sorted(set(actual) - set(before))
    for record_id in sorted(set(before) & set(actual)):
        baseline = before.get(record_id, {})
        observed = actual[record_id]
        approved_fields = approved.get(record_id, {})
        for field, expected in approved_fields.items():
            got = observed.get(field)
            if not values_equal(got, expected):
                mismatches.append({"record_id": record_id, "field": field,
                                   "expected": expected, "actual": scalar(got)})
        for field in sorted((set(baseline) | set(observed)) - {key} - set(approved_fields)):
            if not values_equal(baseline.get(field), observed.get(field)):
                side_effects.append({"record_id": record_id, "field": field,
                                     "before": scalar(baseline.get(field)),
                                     "actual": scalar(observed.get(field))})
    status = "passed" if not (mismatches or side_effects or missing_records or
                               unexpected_records) else "failed"
    return {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "status": status,
        "summary": {
            "affected_records": len(approved),
            "approved_field_changes": len(changeset["changes"]),
            "mismatches": len(mismatches),
            "side_effects": len(side_effects),
            "missing_records": len(missing_records),
            "unexpected_records": len(unexpected_records),
        },
        "mismatches": mismatches,
        "side_effects": side_effects,
        "missing_records": missing_records,
        "unexpected_records": unexpected_records,
    }


def write_verification(out_dir: str, plan_dir: str, verification: Dict[str, Any],
                       sources: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    prepare_output(out_dir, force)
    verification_path = os.path.join(out_dir, "verification.json")
    _write_json(verification_path, verification)
    changeset_path = os.path.join(plan_dir, "changeset.json")
    manifest_path = os.path.join(plan_dir, "manifest.json")
    receipt = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "status": verification["status"],
        "plan": {
            "changeset_sha256": sha256_file(changeset_path),
            "manifest_sha256": sha256_file(manifest_path) if os.path.isfile(manifest_path) else None,
        },
        "sources": sources,
        "verification_sha256": sha256_file(verification_path),
        "summary": verification["summary"],
        "note": "SHA-256 links evidence; this receipt is not an identity signature.",
    }
    _write_json(os.path.join(out_dir, "receipt.json"), receipt)
    return receipt
