# Contributing to LIKAcs

Website: <http://likaapps.com> · Repository: <https://github.com/azyoff/LIKAcs>

Thanks for helping internet cafes run fair LAN matches. LIKAcs is MIT licensed
and free for everyone.

## The one non-negotiable rule

**Every change must stay 100% VAC-safe.** Never add:

- game process memory reads/writes (`ReadProcessMemory`, `WriteProcessMemory`, ...)
- DLL injection, hooks, engine patching or binary edits
- `-insecure` or anything that disables VAC
- cheats, aim assistance, or reading game state from memory

Only these first-party mechanisms are allowed: official `.cfg` files, official
launch parameters, official RCON, Steam `steam://` URLs, and normal OS process
start/stop. `python scripts/verify_vac_safety.py` runs in CI and will fail the
build on violations.

## Development setup

```bash
git clone https://github.com/azyoff/LIKAcs.git
cd LIKAcs
export PYTHONPATH=src                 # Windows: set PYTHONPATH=src
python -m likacs --self-test
python -m unittest discover -s tests -v
python scripts/verify_vac_safety.py
python -m likacs --mode=control       # needs Tkinter
```

Only the **standard library** may be used at runtime. `PyInstaller` is a
build-time-only dependency (`requirements-build.txt`). If you add a module
imported dynamically (inside a function or thread), add it to
`HIDDEN_IMPORTS` in `scripts/build.py`.

## Code style

- Python 3.10+ compatible, type hints on public functions, docstrings on modules.
- Small focused modules; keep `agent.py` / `control.py` as orchestrators.
- Every new LAN endpoint must be HMAC-verified (`security.LanAuth`).
- Add unit tests under `tests/` and update `selftest.py` for anything safety-critical.
- Update `README.md`, `CHANGELOG.md` and the relevant `docs/` page.

## Releasing

1. Bump `VERSION` in `src/likacs/__init__.py`, `pyproject.toml`, `CHANGELOG.md`.
2. Run CI locally (`unittest`, `--self-test`, `verify_vac_safety.py`).
3. Tag `vX.Y.Z` and push, or dispatch `release.yml` with the tag input.
4. The workflow builds all three `.exe`s, generates `SHA256SUMS.txt`, verifies
   the built exe and attaches everything to the GitHub Release. The in-app
   updater then offers it to every cafe laptop.
