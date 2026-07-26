# Development workflow

Solo-friendly trunk-based flow, sized so releasing and iterating stays fast *and* safe.

## Branching & commits

- Work directly on `main` for small changes; use a short-lived branch for anything risky and merge when green.
- Commit style: `<area>: <what changed>` (e.g. `capture: handle Arena subteam payloads`). Small, single-purpose commits — they make "which commit broke capture after the patch?" answerable.
- Keep [PRD.md](PRD.md) in the same commit as the behavior change it describes.

## Local checks (pre-commit)

One-time setup:

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pre-commit install
```

Every commit then automatically runs:
- **ruff** — lint (incl. `S` security rules from bandit) + auto-format
- **gitleaks** — secret scanning (belt-and-suspenders: the app is designed to have no secrets — the LCU token is read from the client process at runtime and never persisted)
- merge-conflict / whitespace hygiene

Run everything manually: `.venv\Scripts\pre-commit run --all-files`

## CI (GitHub Actions)

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push/PR, on a Windows runner (matching the target platform): ruff lint + format check, compile check, the smoke test, and **pip-audit** (dependency CVE scan). Dependabot files weekly PRs for dependency and action updates — CI validates them, so keeping deps fresh is a one-click merge.

## Tests

`tests/smoke_test.py` covers the capture normalizer and the game store end-to-end without needing League running. Rule of thumb: anything that parses LCU payloads or writes to the store gets covered there (or in a new test file) — those are the two places silent breakage hurts.

## Security posture

- **No secrets by design:** no API keys, no accounts, no cloud. The only credential (LCU token) is ephemeral, local, and never written to disk. Gitleaks enforces this stays true.
- **Dependency safety:** pip-audit in CI + Dependabot weekly. Dependencies are deliberately few — every new one is a real decision.
- **Riot/Vanguard constraints:** PRD §6a is non-negotiable review criteria for every change: LCU-only, never touch the game process, nothing in-game, no input automation.
- Data stays in `%LOCALAPPDATA%\LeagueOfKiffance\` — the repo never contains user data.

## Releases (Phase 4)

When share-ready: tag `vX.Y.Z` → a release workflow (to be added in Phase 4) builds the single-exe with PyInstaller on a clean runner and attaches it to a GitHub Release. Building in CI rather than on a dev machine keeps the shipped binary reproducible and clean.
