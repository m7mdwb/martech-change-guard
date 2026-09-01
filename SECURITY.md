# Security policy

## Supported versions

| Version | Security fixes |
|---|---|
| 0.2.x | Yes |
| 0.1.x and earlier | No |

## Reporting a vulnerability

Do not open a public issue or attach a real CRM export. Use
[GitHub private vulnerability reporting](https://github.com/m7mdwb/martech-change-guard/security/advisories/new).

Include the affected command and version, impact, a minimal reproduction using synthetic
data, expected and actual results, and the exit code. Useful reports include malformed input
receiving a safe verdict, an unapproved side effect being missed, unsafe artifact handling,
or an agent workflow crossing the no-live-writes boundary.

We aim to acknowledge reports within five business days and provide an initial assessment
within ten. Never submit production records, customer identifiers, credentials, or tokens.
