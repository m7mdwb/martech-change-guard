# The MarTech safety loop

This walkthrough connects two independent, local-first repositories without giving either
one credentials or permission to write to a production system.

```text
MarTech Verify             MarTech Change Guard            Existing CRM/import tool
diagnose evidence    ->    plan + policy + rollback   ->   separately authorized write
read-only exports          no live write                   canary or approved plan
                                   |
fresh export          <-    verify + receipt          <----+
```

## Scenario

Thirty synthetic leads are tested against six routing rules. MarTech Verify finds that nine
leads fall through to `unassigned`, one rule contains the field typo `employes`, and the
France rule is shadowed by a broader rule above it.

The proposed remediation assigns only the nine unrouted leads. Consent is protected and
must not change. MarTech Change Guard binds the routing report to its changeset, calculates
the blast radius, creates a canary and rollback, and requires review. The first simulated
post-change export contains a planted consent side effect and fails verification; the
corrected export passes.

## 1. Diagnose with MarTech Verify

```bash
python ../martech-verify/skills/routing-simulate/scripts/simulate.py \
  --rules ../martech-verify/fixtures/routing-simulate/routing_rules.json \
  --leads ../martech-verify/fixtures/routing-simulate/leads_sample.csv \
  --json > routing-audit.json
```

Expected evidence: 30 leads, 9 unrouted, a critical unknown field, a shadowed rule, and a
19× owner-load spread. The report diagnoses the problem; it does not authorize a fix.

## 2. Plan and bind the evidence

```bash
python skills/martech-change-guard/scripts/guard.py plan \
  --before fixtures/connected/current-unrouted-leads.csv \
  --proposed fixtures/connected/proposed-routed-leads.csv \
  --key lead_id \
  --policy fixtures/connected/routing-policy.json \
  --evidence routing-audit.json \
  --reason "Route nine leads identified as unassigned by MarTech Verify" \
  --out guard-plan
```

The plan exits `1` (`review`): 9 of 9 scoped records change, only `owner` is approved, and
the evidence digest is stored in `changeset.json`. Nothing has been written to a CRM.

## 3. Approve and execute elsewhere

A human reviews `risk-report.json`, `canary.csv`, and `rollback.csv`. Any write happens with
the existing CRM or import tool and its own permissions. Neither repository contains a
connector or credential.

## 4. Catch a side effect

```bash
python skills/martech-change-guard/scripts/guard.py verify \
  --before fixtures/connected/current-unrouted-leads.csv \
  --actual fixtures/connected/actual-routed-side-effect.csv \
  --key lead_id --plan guard-plan --out failed-verification
```

This exits `1`: all nine owner updates landed, but one protected `consent_status` changed.
The operation is not verified.

Run the same command with `actual-routed-safe.csv`; it exits `0` and creates a receipt bound
to the plan, baseline, exact post-change export, and verification evidence.

## Install both

For Codex:

```text
$skill-installer Install all skills from https://github.com/m7mdwb/martech-verify
$skill-installer Install the skill from https://github.com/m7mdwb/martech-change-guard
```

For Claude Code, either repository marketplace lists both plugins:

```bash
claude plugin marketplace add m7mdwb/martech-change-guard
claude plugin install martech-verify@martech-guard
claude plugin install martech-change-guard@martech-guard
```

The [GIF](martech-ops-loop-demo.gif), [MP4 recording](martech-ops-loop-walkthrough.mp4),
and [provenance](martech-ops-loop-data.json) are generated from these synthetic tool results.
