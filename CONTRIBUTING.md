# Contributing

MarTech Change Guard accepts focused changes that make bulk CRM mutations safer and more
explainable without adding credentials, connectors, or live-write behavior.

Before a pull request:

- reproduce bugs with minimal synthetic exports;
- preserve Python 3.9+ and standard-library-only runtime code;
- keep the skill installable as a standalone folder;
- add deterministic tests for both safe and unsafe cases;
- keep generated README assets current;
- never submit real customer data, credentials, or production URLs.

Run:

```bash
python tests/run_all.py
python tools/make_demo_gif.py --check
```

Every input failure must exit `3` with an actionable message and no traceback. No input
failure may become `allow` or `passed`. Participation is subject to
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
