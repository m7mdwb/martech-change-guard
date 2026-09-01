# Changelog

## 0.2.0 - 2026-09-01

- Detect side effects across the complete post-change export, including untouched records.
- Detect unexpected record additions and deletions during verification.
- Reject schema drift instead of interpreting omitted columns as field clears.
- Harden CSV, TSV, JSON, encoding, binary, ragged-row, duplicate-header, and large-field handling.
- Bind verification receipts to the exact post-change export with SHA-256.
- JSON-encode operation identifiers and field names to prevent spreadsheet formula execution.
- Add adversarial and packaging tests, a generated demo, and marketer-first installation guidance.
- Standardize the human-facing product name as MarTech Change Guard.

## 0.1.0 - 2026-08-31

- Initial deterministic planning, policy, canary, rollback, and verification release.
