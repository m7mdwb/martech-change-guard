---
name: martech-change-guard
description: Preflight and verify proposed bulk changes to CRM or marketing records. Use before imports, cleanup, routing, lifecycle, owner, consent, or enrichment updates, and after execution to detect partial writes or side effects. This skill plans and verifies changes; it does not itself authorize or perform live writes.
---

# MarTech Change Guard

Use the deterministic guard before a bulk data mutation. Do not substitute an LLM review
for the script's changeset, invariant checks, rollback operations, or verification result.

If the request follows a `$martech-audit` finding, treat that finding as rationale rather
than authorization. Preserve the audit's compact change brief and bind its JSON report with
`--evidence <report.json>`. The guard remains responsible for comparing current and proposed
exports and enforcing its own policy.

Resolve `scripts/guard.py` relative to this `SKILL.md` and invoke that resolved absolute
path. Installed plugins run from the user's project, so do not assume `scripts/guard.py`
exists under the current working directory. Keep input and output paths in the user's
workspace; never write plan artifacts into the installed skill or plugin cache.

## Plan a change

Obtain a current-state export and a proposed-state export with the same stable record key.
Export the same columns in both files; schema drift fails closed. Read
[references/input-guide.md](references/input-guide.md) when the files or export scope are
unclear.
If the user has only described a desired transformation, create the proposed export without
touching the live system. Then run:

```bash
python <absolute-skill-directory>/scripts/guard.py plan --before current.csv --proposed proposed.csv \
  --key record_id --policy policy.json --reason "Why this change is needed" \
  --evidence audit-report.json --out guard-plan
```

Read `guard-plan/risk-report.json` and lead with its decision:

- `allow`: the plan passed configured controls, but a live write still requires the user's
  authorization and the destination tool's normal safeguards.
- `review`: show the blast radius, warnings, and canary. Ask for approval immediately before
  any live write.
- `block`: do not execute. Explain each invariant violation and revise the proposal.

Never bypass a block, silently relax a policy, or use `--force` unless the user explicitly
asks to replace that exact plan directory. Record additions and deletions are unsupported in
this version and always block.

For policy fields and examples, read [references/policy-schema.md](references/policy-schema.md).

## Execute outside the guard

This skill deliberately has no CRM credentials and performs no remote writes. If the user
authorizes execution, use the available CRM/API tool to apply only the approved changes.
Prefer the generated canary first when the decision requires review. Stop on any write error
or unexpected response; do not improvise values that are absent from the approved changeset.

## Verify afterward

Export or re-fetch the affected records, then run:

```bash
python <absolute-skill-directory>/scripts/guard.py verify --before current.csv --actual after.csv \
  --key record_id --plan guard-plan --out guard-verification
```

Treat `receipt.json` as the result. `passed` means every approved field reached its expected
value, the record set stayed intact, and no unapproved field changed anywhere in the supplied
scope. `failed` means the operation is not verified; report mismatches, missing or unexpected
records, and side effects before considering rollback. Verification must use a fresh export
of the complete original scope, not only records the write was intended to affect.

Read [references/artifacts.md](references/artifacts.md) when consuming the JSON artifacts or
building an adapter. The receipt is tamper-evident through SHA-256 digests, not cryptographically
signed and not proof of who approved or executed a change.

## Important boundaries

- Preserve source exports and plan artifacts; verification depends on them.
- If the tool exits `3`, stop and present its actionable input error. Never turn an input
  failure into an `allow` or `passed` result.
- Do not include secrets in policies or exports. Outputs repeat changed field values locally.
- A passing file comparison does not prove downstream workflows, emails, billing, or syncs
  behaved correctly unless their resulting fields are present in the post-change export.
- Human approval and tool permissions remain separate from this skill's risk decision.
