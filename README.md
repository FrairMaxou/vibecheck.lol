# League of Kiffance

Tracks whether you're actually *having fun* playing League of Legends. When a game ends, a tiny popup asks "Had fun?" (one click, 1–5). Match data (champion, result, KDA, queue, teammates) is captured automatically from the League client's local API. Over time, the data shows which champions, friends, and situations bring you kiffance — and which don't.

**Privacy & safety:** everything stays local on your machine (SQLite). The tool only talks to the League client's official local API (the same one apps like Blitz use) — it never touches the game process, shows nothing in-game, and automates nothing. See [PRD.md](PRD.md) §6a.

## Requirements

- Windows 10/11
- Python 3.10+
- League of Legends installed

## Setup

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Run

```powershell
# with console logs (development)
.venv\Scripts\python -m kiffance

# silent, tray-only (daily use)
.venv\Scripts\pythonw -m kiffance
```

A smiley coin appears in the system tray. Play a game — when it ends, rate it. That's it.

Data and logs live in `%LOCALAPPDATA%\LeagueOfKiffance\`.

## Status

Phase 1 (capture loop) — see [PRD.md](PRD.md) for the roadmap. The insights dashboard is Phase 2.
