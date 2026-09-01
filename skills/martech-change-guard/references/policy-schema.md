# Policy schema

The policy is a JSON object. Every field is optional; omitted fields use conservative
defaults.

```json
{
  "allowed_fields": ["lifecycle_stage", "lead_source"],
  "protected_fields": ["owner", "opted_out"],
  "immutable_fields": ["created_at", "original_source"],
  "fill_only_fields": ["lead_source"],
  "monotonic_fields": {
    "lifecycle_stage": ["lead", "mql", "sql", "opportunity", "customer"]
  },
  "approval_required_over_records": 100,
  "approval_required_over_percent": 10,
  "hard_limit_records": 10000,
  "hard_limit_percent": 80,
  "risk_weights": {
    "lifecycle_stage": 15,
    "owner": 25
  }
}
```

## Field behavior

- `allowed_fields`: when non-empty, any changed field outside the list blocks.
- `protected_fields`: any change blocks.
- `immutable_fields`: any change blocks. Kept separate so reports can distinguish business
  immutability from operational protection.
- `fill_only_fields`: empty to non-empty is allowed; overwriting or clearing blocks.
- `monotonic_fields`: values may remain at the same position or move forward in the given
  order. Regressions and unknown values block.
- `approval_required_over_records` and `approval_required_over_percent`: exceeding either
  changes an otherwise allowed plan to `review`.
- `hard_limit_records` and `hard_limit_percent`: exceeding either blocks.
- `risk_weights`: adds a 0–50 score once per changed field. Weights influence review priority
  but never cancel invariant violations.

Defaults require review above 100 records or 10%, and block above 10,000 records. The
default percentage hard limit is 100%; set a lower value when your operating policy requires it.
Additions, deletions, duplicate IDs, missing IDs, and mismatched export schemas always fail
closed in V1.

Empty means `null`, an empty string, or whitespace. Text comparisons for monotonic fields
are case-insensitive; original values are preserved in artifacts.
