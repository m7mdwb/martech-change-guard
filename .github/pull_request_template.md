## What changed

Describe the user-visible safety or usability problem and the smallest change that fixes it.

## Evidence

Explain the synthetic fixture and test that prove the behavior. State what remains outside
the tool’s visibility.

## Checklist

- [ ] Tests cover unsafe and safe cases, or this is documentation-only.
- [ ] `python tests/run_all.py` passes.
- [ ] `python tools/make_demo_gif.py --check` passes.
- [ ] Runtime code remains Python 3.9+ standard-library only.
- [ ] No connector, credential, telemetry, or live write was added.
- [ ] Examples contain no real customer data or credentials.
