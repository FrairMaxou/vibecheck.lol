# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

**Phase 1 (capture loop) is implemented.** The project is specified in [PRD.md](PRD.md) (v0.2, all decisions locked) — this file summarizes what's binding; the PRD is the source of truth and should be kept in sync when decisions change. Phases 2–4 (dashboard, tags/insights, packaging) are not started.

## Commands

```powershell
.venv\Scripts\pip install -r requirements.txt   # deps (venv already exists)
.venv\Scripts\python -m kiffance                # run with console logs (dev)
.venv\Scripts\pythonw -m kiffance               # run silent, tray-only
.venv\Scripts\python tests\smoke_test.py        # capture+store smoke test (no League needed)
.venv\Scripts\ruff check . --fix                # lint (incl. security rules)
.venv\Scripts\ruff format .                     # format
.venv\Scripts\pre-commit run --all-files        # everything the commit hook runs
```

Workflow (see [CONTRIBUTING.md](CONTRIBUTING.md)): trunk-based on `main`, commits styled `<area>: <what>`, pre-commit hooks (ruff + gitleaks) enforced locally, CI on GitHub Actions runs lint/format/smoke-test/pip-audit on a Windows runner. Keep PRD.md and CLAUDE.md in the same commit as the behavior change they describe.

Runtime data and logs: `%LOCALAPPDATA%\LeagueOfKiffance\` (`kiffance.sqlite3`, `kiffance.log`).

## Code map

- [kiffance/lcu.py](kiffance/lcu.py) — the ONLY module that talks to the LCU: client discovery via process cmdline, REST client, gameflow WebSocket subscription. LCU endpoint changes land here.
- [kiffance/store.py](kiffance/store.py) — the ONLY module that touches SQLite (the "game store" interface from PRD §11). Feature code never issues SQL.
- [kiffance/capture.py](kiffance/capture.py) — normalizes the end-of-game payload; deliberately defensive (payload shapes drift across patches), never raises, always keeps the raw payload.
- [kiffance/app.py](kiffance/app.py) — orchestration and threading: main thread = Tk (popup), watcher thread = LCU WebSocket (blocks; reconnects when the client restarts), tray thread = pystray. Cross-thread UI goes through the `_popup_request` queue — never call Tk from the watcher thread.
- [kiffance/popup.py](kiffance/popup.py), [kiffance/tray.py](kiffance/tray.py) — rating popup (F7–F10b) and tray icon (F22).
- [kiffance/config.py](kiffance/config.py) — paths, tracked queue IDs (F3b), timeouts.

## What this is

League of Kiffance: a personal Windows tray tool that detects the end of each League of Legends game via the **LCU API** (the League client's local REST/WebSocket API — no Riot web API key involved), auto-captures match data to SQLite, shows a one-click "Had fun?" popup (1–5 emoji scale), and serves a localhost dashboard with fun-vs-champion/friends/context insights.

## Locked decisions (PRD §9 — don't relitigate)

- **Stack:** Python — tray app (`pystray`), LCU via lockfile + `httpx`/`willump`, FastAPI + Chart.js dashboard, stdlib `sqlite3`.
- **Rating:** 1–5 emoji, always-on-top popup; hides instantly if a new game starts (game goes to a "pending rating" list, rateable later from the dashboard).
- **Tracked queues:** ALL queues are captured, including Arena and rotating modes. `QUEUE_NAMES` in config.py only provides friendly labels; unknown queue ids fall back to the payload's raw queue name. Never reintroduce capture-time filtering — mode filtering belongs in the dashboard.
- **UI language:** English. Tags/notes are Phase 3, not Phase 1.
- **Startup:** manual launch by default; opt-in "start with Windows" checkbox.
- **Social:** v1 is fully local per player (GitHub distribution). No hosted backend, no webhooks.

## Hard constraints — never violate (PRD §6a, §6b, §11)

1. **Vanguard safety:** LCU local API only; never touch the game process (no memory reads, injection, hooks, screen capture); no in-game overlay or popup during live gameplay; no input automation. Reject any feature that breaks these.
2. **Lightweight:** event-driven via LCU WebSocket (`OnJsonApiEvent` gameflow events), never busy-poll; single process; dashboard binds localhost only, may start lazily; ~<100 MB RAM target.
3. **Future-proofing for social:** all persistence goes through a single "game store" interface — no raw SQLite calls scattered in feature code. Players keyed by PUUID. Store the raw LCU end-of-game JSON payload alongside normalized fields.

## Architecture (PRD §6)

Single process: LCU watcher (WebSocket) → on game end, fetch end-of-game stats → persist via game store → rating popup → SQLite; FastAPI serves the dashboard from the tray menu. The LCU API is unofficial and can shift with patches — keep LCU calls behind a thin adapter layer and log loudly when an endpoint fails.

## Phasing (PRD §7)

1. Capture loop: LCU connection, game-end detection, SQLite persistence, basic rating popup. Exit criterion: 3 real games recorded and rated with no manual step besides the rating click.
2. Dashboard insights (champion/squad/context, pending-ratings page; every stat shows sample size, <5 games = "not enough data yet").
3. Tags, fun-facts cards, session analysis, remake handling, missed-game catch-up import.
4. Share-ready: single-exe release, friend-proof README, JSON/CSV export.
