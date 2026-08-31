# Artifact contract

## Plan artifacts

- `changeset.json`: SHA-256 source fingerprints, field-level before/after values, record counts, and
  added/removed IDs. This is the approved unit of work.
- `risk-report.json`: `allow`, `review`, or `block`; deterministic score and level; blast
  radius; invariant violations; and warnings.
- `canary.csv`: a deterministic, diverse subset of changed records. Rows are field-level
  operations, not full record replacements.
- `rollback.csv`: inverse field-level operations with the value expected after execution.
  An adapter should use that expected value as an optimistic-concurrency check.
- `manifest.json`: SHA-256 hashes of the other plan artifacts.

## Verification artifacts

- `verification.json`: expected-field mismatches, missing records, and changes to fields that
  were not approved on affected records.
- `receipt.json`: final `passed` or `failed` status and hashes linking the receipt to the plan
  and verification evidence.

Verification refuses a changeset whose digest no longer matches `manifest.json`, and refuses
a `--before` file whose digest differs from the one recorded at plan time.

## Adapter invariants

An external CRM adapter should:

1. consume only field operations from `changeset.json`;
2. preserve the record ID as an opaque string;
3. compare the live current value to `before` immediately before writing;
4. stop on a mismatch instead of overwriting concurrent work;
5. apply only an explicitly approved canary or full plan;
6. re-read written records and run `verify`;
7. never treat HTTP success as verification.

Artifacts may contain CRM field values. Store them with the same controls as the source
exports and do not commit real customer data to a repository.
