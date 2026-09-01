# Input guide

MarTech Change Guard uses three local exports from the same CRM object and scope.

| File | When | Meaning |
|---|---|---|
| `before` | Before any write | The current source of truth |
| `proposed` | Before approval | The exact state you intend to create |
| `actual` | After execution | A fresh export used for verification |

Export the same columns in all three files and include one stable, unique record ID. The
guard refuses schema drift because an omitted column must never be mistaken for permission
to clear a field. CSV, TSV, semicolon-delimited files, JSON arrays, JSON Lines, UTF-8, a UTF-8
BOM, and common Windows-1252 spreadsheet exports are supported.

Use synthetic data when testing. Real exports and generated artifacts may contain customer
data, so keep them out of source control and apply the same retention and access controls as
the CRM itself.

The `proposed` export is not an instruction to write. It is review material. A separate CRM
or import tool performs any authorized update, preferably on the generated canary first.
Afterward, export the entire original scope—not only the changed records—so verification can
detect side effects on records that were supposed to remain untouched.
