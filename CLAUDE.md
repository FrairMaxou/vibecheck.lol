# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

This file is an **index**. It holds only what must be in context on every turn —
how to answer, what the app is, where the code lives, and what can never be
violated. Everything else lives in a narrower file listed below; read that file
when the work calls for it, not before.

## How to respond — be concise

Default to a few lines. The user reads every word; padding wastes their time.

- **Answer first.** State the finding or the action, then stop. No preamble, no
  restating the question, no summary of what you just said.
- **Cut the teaching.** Don't explain mechanisms, trade-offs, or background
  unless asked or unless it changes what the user should do.
- **No status theatre.** Skip "what I did / what's next / where things stand"
  recaps and end-of-turn tables. Report what changed in one line.
- **One suggestion, not a menu.** Pick the best option and say it. Offer
  alternatives only when the choice is genuinely the user's.
- Keep tables and headers for genuinely structured data (queue ids, check
  results) — not to organise two sentences.
- Flag real problems in one sentence. Caveats earn their place only if acting
  on them would change the outcome.

Verbosity in *code comments* is different — keep explaining the non-obvious
"why" there, per the repo's existing style.

## Three gates — non-negotiable

These are gates, not guidelines: each one blocks a step until it's satisfied.
They exist because the three moments below are where a wrong turn is cheapest to
catch and most expensive to miss.

**1. Before writing a plan.** Do not produce a plan until you have **over 96%
confidence you know what you are planning for.** Below that, ask follow-up
questions until you reach it. A plan built on a guess costs a day; a question
costs a message. "I'll figure it out while implementing" is not confidence.

**2. Immediately after submitting a plan.** Review your own plan and identify
the parts that introduce the most **product** risk — risk to users, to their
data, to the release — not just technical difficulty. List them **most risky
first**, then extend the plan with a concrete step that reduces each one. A risk
named without a mitigation is decoration.

**3. Before opening a PR or deploying anything.** Act as a senior engineer and
do a **thorough code review of your own work**. Identify every error,
inconsistent logic, inefficiency, and anything that can create a bug. List the
findings **most critical first, before fixing them** — then fix them. Report
what you found in the PR, including what you checked and could *not* verify.
"CI is green" is not a review; CI only runs the checks that already exist.

## What this is

**VibeCheck.lol** — a Windows tray app that detects the end of each League of
Legends game via the **LCU API** (the League client's local REST/WebSocket API;
no Riot web API key involved), auto-captures the match to SQLite, shows a
one-click "Had fun?" popup (1–5 emoji scale), and serves a localhost dashboard
with fun-vs-champion/friends/context insights.

Shipped and public — real users are on it, so **treat `main` as production**.
All four PRD phases are done, plus one-click self-update, anonymous telemetry,
a Discord feedback link and a what's-new card. Current version lives in
`vibecheck/config.py` (`APP_VERSION`) and on the
[releases page](https://github.com/FrairMaxou/vibecheck.lol/releases).

## Where things are written down

Read the narrow file, not everything. This file stays small on purpose.

| File | What's in it | When to read |
|---|---|---|
| `.claude/PREFERENCES.md` | Do / don't — the maintainer's standing preferences | **Every session, before proposing anything** |
| `.claude/brand identity/BRAND.md` | Palette, fonts, logo, voice, tier scale | **Before any visual/UI change** |
| `.claude/GOTCHAS.md` | Live traps: prod drift, telemetry blind spots | Before touching Supabase, telemetry or the updater |
| [PRD.md](PRD.md) | Full spec and locked decisions (§9) | Questions about intended behaviour |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Branching, Conventional Commits, hooks, CI | Committing or opening a PR |
| [docs/RELEASE.md](docs/RELEASE.md) | Deployment protocol + release checklist | Shipping a version |
| [docs/MONITORING.md](docs/MONITORING.md) | Supabase Studio dashboard setup | Maintainer analytics |
| [GitHub Issues](https://github.com/FrairMaxou/vibecheck.lol/issues) | The backlog — one issue per unit of work | Picking up or planning work |

Files under `.claude/` are maintainer-local: they are gitignored here and backed
up in a separate private repo. Keep new long-form notes in their own file with a
row in this table — don't grow this one.

## Commands

```powershell
.venv\Scripts\pip install -r requirements.txt   # deps (venv already exists)
.venv\Scripts\python -m vibecheck               # run with console logs (dev)
.venv\Scripts\pythonw -m vibecheck              # run silent, tray-only
.venv\Scripts\python tests\smoke_test.py        # capture+store smoke test (no League needed)
.venv\Scripts\ruff check . --fix                # lint (incl. security rules)
.venv\Scripts\ruff format .                     # format
.venv\Scripts\pre-commit run --all-files        # everything the commit hook runs
```

Runtime data and logs: `%LOCALAPPDATA%\VibeCheck\` (`vibecheck.sqlite3`,
`vibecheck.log`).

## Workflow in one paragraph

Work is tracked as GitHub Issues. One issue → one branch (`<type>/<issue>-<slug>`)
→ one PR that says `Closes #N` → CI green → squash-merge. **Commit messages and
PR titles follow [Conventional Commits](https://www.conventionalcommits.org)**
(`feat(capture): …`, `fix(sync): …`) — enforced by a `commit-msg` hook locally
and a PR-title check in CI. The convention is load-bearing, not cosmetic:
`release-please` derives the next version from those types and keeps a Release
PR open — merging it tags and ships. Keep PRD.md, CLAUDE.md and the docs in the
same commit as the behaviour change they describe.
Details: [CONTRIBUTING.md](CONTRIBUTING.md), [docs/RELEASE.md](docs/RELEASE.md).

## Code map

- [vibecheck/lcu.py](vibecheck/lcu.py) — the ONLY module that talks to the LCU: client discovery via process cmdline, REST client, gameflow WebSocket subscription. LCU endpoint changes land here.
- [vibecheck/store.py](vibecheck/store.py) — the ONLY module that touches SQLite (the "game store" interface from PRD §11). Feature code never issues SQL.
- [vibecheck/capture.py](vibecheck/capture.py) — normalizes the end-of-game payload; deliberately defensive (payload shapes drift across patches), never raises, always keeps the raw payload.
- [vibecheck/app.py](vibecheck/app.py) — orchestration and threading: main thread = Tk (popup), watcher thread = LCU WebSocket (blocks; reconnects when the client restarts), tray thread = pystray. Cross-thread UI goes through the `_popup_request` queue — never call Tk from the watcher thread.
- [vibecheck/popup.py](vibecheck/popup.py), [vibecheck/tray.py](vibecheck/tray.py) — rating popup (F7–F10b) and tray icon (F22).
- [vibecheck/sync.py](vibecheck/sync.py), [vibecheck/telemetry.py](vibecheck/telemetry.py), [vibecheck/updater.py](vibecheck/updater.py) — Supabase squad sync, anonymous usage ping, one-click self-update.
- [vibecheck/config.py](vibecheck/config.py) — `APP_VERSION`, paths, queue labels, timeouts.

## Architecture (PRD §6)

Single process: LCU watcher (WebSocket) → on game end, fetch end-of-game stats →
persist via game store → rating popup → SQLite; FastAPI serves the dashboard from
the tray menu. The LCU API is unofficial and shifts with patches — keep LCU calls
behind a thin adapter layer and log loudly when an endpoint fails.

## Hard constraints — never violate (PRD §6a, §6b, §11)

1. **Vanguard safety:** LCU local API only; never touch the game process (no memory reads, injection, hooks, screen capture); no in-game overlay or popup during live gameplay; no input automation. Reject any feature that breaks these.
2. **Lightweight:** event-driven via LCU WebSocket (`OnJsonApiEvent` gameflow events), never busy-poll; single process; dashboard binds localhost only, may start lazily; ~<100 MB RAM target.
3. **Future-proofing for social:** all persistence goes through the single game-store interface — no raw SQLite calls scattered in feature code. Players keyed by PUUID. Store the raw LCU end-of-game JSON payload alongside normalized fields.

## Locked decisions (PRD §9 — don't relitigate)

Full text in the PRD. The ones most often re-proposed by mistake:

- **All queues are captured**, Arena and rotating modes included. `QUEUE_NAMES`
  only supplies friendly labels; unknown ids fall back to the payload's raw
  name. Never reintroduce capture-time filtering — filtering belongs in the
  dashboard.
- **Zero-config squads** (PRD §12): identity is the in-game PUUID, auth is a
  silent Supabase anonymous session, and a squad is *mutual* League friends who
  also run VibeCheck. No accounts, no email/password, no invite codes — don't
  reintroduce them without changing the PRD first.
- **Stack:** Python — `pystray` tray, LCU via lockfile + `httpx`/`willump`,
  FastAPI + Chart.js dashboard, stdlib `sqlite3`.
- **UI language is English.** Startup is manual by default, with an opt-in
  "start with Windows" checkbox.
