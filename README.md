# MarTech Change Guard

**One question: is it safe to make this change?** Preventive, before the fact, one
workflow from plan to receipt.

GitHub gives code a diff, tests, review, and rollback. Martech Change Guard brings the
same discipline to bulk CRM and marketing-data changes.

> Companion project: **[martech-verify](https://github.com/m7mdwb/martech-verify)** answers the
> other half, *what is wrong with this data?* — four read-only checks for PII leakage, campaign
> tagging, conversion gaps and lead routing. Same rules: local exports, no connectors, no
> dependencies.

It compares a current export with a proposed export, produces the exact field-level
changeset, enforces business invariants, estimates blast radius, selects a deterministic
canary, and generates rollback operations. After execution, it compares a fresh export to
the approved plan and issues a tamper-evident receipt.

**It does not connect to or write to your CRM.** V1 is a local safety layer around whatever
CRM, API, import tool, Claude connector, or Codex connector you already use.

## What it catches

- lifecycle stages moving backward;
- protected or immutable fields changing;
- enrichment overwriting values it was only allowed to fill;
- updates outside an explicit field allowlist;
- unexpectedly large record or percentage blast radius;
- additions or deletions disguised as an update;
- partial writes and unexpected side effects after execution.

Python 3.9+ and the standard library are the only runtime requirements. CSV, TSV, JSON arrays,
and JSON Lines are supported.

## Try the planted failure

```bash
python skills/martech-change-guard/scripts/guard.py plan \
  --before fixtures/current.csv \
  --proposed fixtures/proposed-blocked.csv \
  --key record_id \
  --policy fixtures/policy.json \
  --out guard-plan
```

The command exits `2` and explains why the plan is blocked. Try the safe proposal instead:

```bash
python skills/martech-change-guard/scripts/guard.py plan \
  --before fixtures/current.csv \
  --proposed fixtures/proposed-safe.csv \
  --key record_id \
  --policy fixtures/policy.json \
  --out guard-plan
```

That plan requires review because it touches 60% of this deliberately tiny fixture. Verify
the simulated result:

```bash
python skills/martech-change-guard/scripts/guard.py verify \
  --before fixtures/current.csv \
  --actual fixtures/actual-safe.csv \
  --key record_id \
  --plan guard-plan \
  --out guard-verification
```

## Install for Claude Code

```text
/plugin marketplace add m7mdwb/martech-change-guard
/plugin install martech-change-guard@martech-guard
```

Then invoke `/martech-change-guard:martech-change-guard` or ask Claude to preflight a CRM
bulk change.

## Install as an Agent Skill

The skill follows the portable Agent Skills layout used by Codex, Claude Code, and other
compatible agents:

```bash
npx skills add m7mdwb/martech-change-guard --skill martech-change-guard
```

You can also copy `skills/martech-change-guard` into your agent's skills directory.

## Decisions and exit codes

| Command | Exit | Meaning |
|---|---:|---|
| `plan` | 0 | Policy checks passed; external authorization is still required for a write |
| `plan` | 1 | Review and approval required |
| `plan` | 2 | Blocked by an invariant or unsupported record-set change |
| `verify` | 0 | Approved changes verified with no detected side effects |
| `verify` | 1 | Mismatch, missing record, or side effect detected |
| either | 3 | Input, policy, or output error |

## Design boundaries

- Risk scores are deterministic heuristics, not calibrated probabilities.
- Receipts use SHA-256 digests for tamper evidence; they are not identity signatures.
- Verification covers fields present in the supplied exports. It cannot observe an email,
  workflow, billing event, or downstream sync unless that outcome is exported too.
- V1 supports updates only. Record additions and deletions block because their rollback
  semantics vary too much across CRMs.

## Tests

```bash
python tests/run_all.py
```

MIT licensed.
