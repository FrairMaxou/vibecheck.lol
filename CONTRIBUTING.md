# Development workflow

Solo-friendly trunk-based flow, sized so releasing and iterating stays fast *and*
safe. `main` is production — real users self-update from it.

## The loop

Work is tracked as [GitHub Issues](https://github.com/FrairMaxou/vibecheck.lol/issues).
One issue is one unit of work.

1. **Pick an issue** (or open one — every non-trivial change should have one).
2. **Branch** from `main`: `<type>/<issue>-<slug>`, e.g. `fix/42-arena-subteams`.
   Small, obvious changes can go straight to a branch without an issue.
3. **Commit** in small, single-purpose steps — they make "which commit broke
   capture after the patch?" answerable.
4. **Open a PR** whose body contains `Closes #42`. That one line closes the
   issue and moves its board card to Done when the PR merges.
5. **CI green → squash-merge → delete the branch.**

## Conventional Commits

Every commit message **and every PR title** follows
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <subject>
```

The PR title matters most: we squash-merge, so **the PR title is the commit
message that lands on `main`**. It is what release notes and any future
changelog are generated from.

**Types**

| Type | Use for |
|---|---|
| `feat` | A user-visible capability that wasn't there before |
| `fix` | A bug users could hit |
| `perf` | Same behaviour, measurably faster or lighter |
| `refactor` | Internal restructuring, no behaviour change |
| `docs` | README, PRD, CLAUDE.md, anything in `docs/` |
| `test` | Tests only |
| `build` | Packaging, PyInstaller spec, dependencies |
| `ci` | GitHub Actions, pre-commit config |
| `chore` | Everything else, including `chore(release): vX.Y.Z` |
| `revert` | Undoing a previous commit |

**Scopes** are optional but should come from this list — a typo'd scope
fragments the history into categories nobody reads:

`capture` · `lcu` · `store` · `app` · `popup` · `tray` · `dashboard` · `web` ·
`sync` · `telemetry` · `updater` · `startup` · `config` · `brand` · `release` ·
`deps` · `deps-dev`

**Subject**: lowercase, imperative, says what changed — not which files moved.

```
feat(dashboard): split League Classic out of the main stats
fix(sync): stop losing the rotated refresh token
chore(release): v0.1.9
```

Breaking changes get a `!` (`feat(store)!: …`) and a `BREAKING CHANGE:` footer.
For this app that mostly means the Supabase schema — see below, old clients stay
live forever.

Both ends are enforced: a `commit-msg` pre-commit hook locally, and a
`pr-title` job in CI.

## Local checks (pre-commit)

One-time setup:

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pre-commit install
```

`default_install_hook_types` in `.pre-commit-config.yaml` is what makes that one
command install the `commit-msg` hook as well as the `pre-commit` one — without
it, `pre-commit install` silently leaves commit messages unchecked. If you set
this repo up before that line existed, re-run the command.

Every commit then runs:

- **conventional-pre-commit** — commit message format (`commit-msg` stage)
- **ruff** — lint (incl. `S` security rules from bandit) + auto-format
- **gitleaks** — secret scanning (belt-and-suspenders: the app is designed to
  have no secrets — the LCU token is read from the client process at runtime and
  never persisted)
- merge-conflict / whitespace hygiene

Run everything manually: `.venv\Scripts\pre-commit run --all-files`

## CI (GitHub Actions)

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push to
`main` and every PR:

- `pr-title` — Conventional Commits check on the PR title (PRs only)
- `checks` — on a Windows runner matching the target platform: ruff lint +
  format check, compile check, the smoke test, and **pip-audit** (dependency CVE
  scan)

Dependabot files weekly PRs for dependency and action updates — CI validates
them, so keeping deps fresh is a one-click merge.

## Tests

`tests/smoke_test.py` covers the capture normalizer and the game store
end-to-end without needing League running. Rule of thumb: anything that parses
LCU payloads or writes to the store gets covered there (or in a new test file) —
those are the two places silent breakage hurts.

## Security posture

- **No secrets by design:** no API keys committed, no accounts, no user
  passwords. The LCU token is ephemeral, local, and never written to disk. The
  Supabase *publishable* key is baked in at build time from CI secrets and is
  public-by-design — see [docs/RELEASE.md](docs/RELEASE.md). Gitleaks enforces
  that nothing secret lands in the repo.
- **Dependency safety:** pip-audit in CI + Dependabot weekly. Dependencies are
  deliberately few — every new one is a real decision.
- **Riot/Vanguard constraints:** PRD §6a is non-negotiable review criteria for
  every change: LCU-only, never touch the game process, nothing in-game, no
  input automation.
- **Backend compatibility:** never make a breaking Supabase schema change. Old
  clients are live and cannot be forced to upgrade.
- Data stays in `%LOCALAPPDATA%\LeagueOfKiffance\` — the repo never contains
  user data.

## Releases

Tag `vX.Y.Z` → [release.yml](.github/workflows/release.yml) builds the single-exe
with PyInstaller on a clean runner and attaches it, plus `SHA256SUMS.txt`, to a
GitHub Release. Building in CI rather than on a dev machine keeps the shipped
binary reproducible and clean. Full protocol and checklist:
[docs/RELEASE.md](docs/RELEASE.md).
