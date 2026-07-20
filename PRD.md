# PRD — League of Kiffance

**Version:** 0.2
**Author:** Maxime Gosselin
**Date:** 2026-07-20
**Status:** Decisions locked — ready to build

---

## 1. Overview

League of Kiffance is a small personal desktop tool that answers one question over time: **"When do I actually have fun playing League of Legends?"**

Stats sites (op.gg, u.gg, League client) tell you how well you played. None of them tell you whether you *enjoyed* it. This tool captures a one-tap "fun rating" right after each game, pairs it with the full match data (champion, role, teammates, result, duration, queue…), and turns the accumulated history into insights like:

- "You rate Jhin games 4.2/5 but Yasuo games 1.8/5 — even though you win more on Yasuo."
- "Games with Alex in the lobby: 85% fun. Solo queue after 11pm: 20% fun."
- "Your fun drops off a cliff after the 3rd game of a session."

**Core loop:** play game → tool detects game end → quick "was it fun?" prompt → data saved → insights dashboard updates.

---

## 2. Goals & Non-Goals

### Goals
- **Zero-friction capture.** The only manual action is the fun rating itself (one click, < 5 seconds). Everything else is automatic.
- **Never miss a game.** Match data is fetched automatically; if a rating is skipped, the game is still recorded and can be rated later.
- **Real-time, fun insights.** Dashboard updates as soon as a game is rated. Insights should feel playful, not like a spreadsheet.
- **Local & private.** All data stays on my machine.
- **Lightweight.** A quiet tray process — near-zero CPU when idle, small memory footprint, no overlay, nothing that competes with the game for resources.
- **Vanguard-safe by design.** Interacts only with the officially tolerated LCU local API, outside of live gameplay. See §6a.

### Non-Goals (v1)
- Shared/hosted data between friends — v1 is fully local per player, but the code must keep the door open (see §11).
- Coaching or performance analysis (this is about *fun*, not improvement).
- Mobile app.
- In-game overlay (Riot-compliance gray zone; a post-game desktop prompt is enough).
- Historical backfill of games played before install (nice-to-have, see §9).

---

## 3. User Stories

1. As a player, when my game ends, I want a small prompt asking if I had fun, so I can answer in one click while the memory is fresh.
2. As a player, I want the tool to record my champion, role, result, KDA, queue, duration, and lobby teammates automatically, so I never fill in anything.
3. As a player, I want to see which champions I actually enjoy, so I can pick for fun and not just winrate.
4. As a player, I want to see how playing with specific friends affects my fun, so I know who my "kiffance enablers" are.
5. As a player, I want to see fun trends by time of day, day of week, session length, and win/loss, so I can spot when I should just stop playing.
6. As a player, if I miss or dismiss the prompt (e.g. instant-queued into the next game), I want to rate pending games later from the dashboard.
7. As a player, I want the tool to start with Windows and sit quietly in the system tray, so I never think about launching it.

---

## 4. Functional Requirements

### 4.1 Game detection & data capture (automatic)

| ID | Requirement | Priority |
|----|-------------|----------|
| F1 | Detect that the League client is running and connect to the local LCU API (lockfile in the League install dir gives port + auth token). | Must |
| F2 | Detect end-of-game via the LCU gameflow phase (`EndOfGame` / `PreEndOfGame`). | Must |
| F3 | On game end, fetch the match summary from the LCU end-of-game stats endpoint: champion, role/position, queue type, win/loss, KDA, CS, game duration, game start time, all 10 participants with summoner names, and which teammates were lobby premades. | Must |
| F3b | **Every queue is captured and prompted** — Ranked, Normals, ARAM, Arena, and all rotating modes (ARAM Mayhem, URF, etc.). Known queue ids get friendly labels; unknown ids are stored with the payload's raw queue name so brand-new modes are captured automatically with no code change. | Must |
| F4 | Persist the raw match payload as-is (JSON blob) alongside the normalized fields, so future insight ideas don't require replaying games. | Must |
| F5 | Handle remakes and dodges gracefully (record as `remake`, don't prompt for fun). | Should |
| F6 | Survive crashes and restarts (game crash, client restart, tool not running): on connect and on returning to lobby, sweep LCU match history for finished games newer than a stored watermark and not yet in the DB; import them and prompt for the newest (older ones go to pending). First launch looks back 3h max — no deep backfill. *(Implemented early — pulled forward from Phase 3 after a real game crash during testing.)* | Must |

### 4.2 Fun rating prompt

| ID | Requirement | Priority |
|----|-------------|----------|
| F7 | Within ~10s of game end, show a small always-on-top popup (not a full window): **"Had fun?"** with a 1–5 scale (😡 😕 😐 🙂 🤩). | Must |
| F8 | One click on a rating saves and dismisses the popup. Total interaction < 5 seconds. | Must |
| F9 | Optional (never required, Phase 3): quick tags after rating — e.g. `tilted`, `carried`, `good squad`, `troll in team`, `clutch` — and a free-text note. Tag list is user-editable. | Should |
| F10 | Popup auto-dismisses after 5 minutes; the game is stored as "pending rating". | Must |
| F10b | If a new game starts while the popup is visible, it hides immediately (never on screen during gameplay) and the game is stored as "pending rating". | Must |
| F11 | Pending games can be rated later from the dashboard (with match context shown as a memory aid). | Must |
| F12 | A "skip this one" option marks a game as intentionally unrated (excluded from stats, stops nagging). | Should |

### 4.3 Insights dashboard

| ID | Requirement | Priority |
|----|-------------|----------|
| F13 | Local web dashboard (e.g. `localhost:port`), openable from the tray icon. | Must |
| F13b | **Global filter bar on every view:** date range, queue/mode, champion, role, teammate, win/loss, session. Filters combine, apply to all charts and fun-facts simultaneously, and persist while navigating. | Must |
| F13c | **Free exploration:** an "explorer" view where the user picks the grouping dimension themselves (fun by champion / teammate / queue / role / day / hour / game-number-in-session / win-loss) and the display style (bar, line, scatter, table) — the canned views (F14–F18) are curated shortcuts, not the only way in. | Must |
| F14 | **Champion kiffance:** avg fun per champion (min. games threshold), fun vs. winrate scatter ("fun but losing" / "winning but miserable" quadrants). | Must |
| F15 | **Squad kiffance:** avg fun when playing with each recurring premade teammate vs. solo. | Must |
| F16 | **Context kiffance:** fun by role, queue type, win/loss, game duration bucket, time of day, day of week. | Must |
| F17 | **Session analysis:** fun by game number within a session (a session = games separated by < 1h) — the "when should I stop?" chart. | Should |
| F18 | **Trend line:** rolling average fun over time. | Should |
| F19 | Headline "fun facts" cards in plain language ("Average fun with Alex: 4.1 ⭐ — solo: 2.9 ⭐"), regenerated live as data comes in. | Should |
| F20 | Tag breakdown: which tags correlate with high/low fun. | Could |
| F21 | Every stat states its sample size; insights with < 5 games are shown as "not enough data yet" rather than noise. | Must |

### 4.4 App shell

| ID | Requirement | Priority |
|----|-------------|----------|
| F22 | Runs as a Windows system-tray app; tray menu: open dashboard, pause prompts, quit. | Must |
| F23 | Manual launch by default, with a settings checkbox to enable "start with Windows" for users who want set-and-forget. | Should |
| F24 | Works whether the tool is started before or after the League client. Reconnects automatically if the client restarts. | Must |

---

## 5. Data Model (SQLite)

```
games
  id INTEGER PK
  riot_match_id TEXT UNIQUE      -- for dedup / potential Riot API cross-ref
  played_at DATETIME
  queue_type TEXT                -- ranked solo, flex, aram, normal, arena...
  champion TEXT
  role TEXT
  win INTEGER                    -- 1/0, NULL for remake
  kills / deaths / assists INTEGER
  cs INTEGER
  duration_seconds INTEGER
  session_id INTEGER             -- computed: games < 1h apart share a session
  game_index_in_session INTEGER
  is_remake INTEGER
  raw_payload TEXT               -- full JSON from LCU (F4)

ratings
  game_id FK -> games (1:1)
  fun_score INTEGER              -- 1..5, NULL = pending
  skipped INTEGER                -- 1 = intentionally unrated
  rated_at DATETIME
  note TEXT

game_teammates
  game_id FK -> games
  summoner_name TEXT
  riot_puuid TEXT                -- stable ID; names change
  was_premade INTEGER            -- in my lobby vs random

tags
  id, label TEXT

game_tags
  game_id FK, tag_id FK
```

Friends are identified by PUUID (stable across name changes); the dashboard shows their latest known name.

---

## 6. Technical Architecture

```
┌─────────────────────────── tray app (single process) ──────────────────────────┐
│                                                                                │
│  LCU watcher ──► game-end event ──► data capture ──► SQLite ◄── rating writes  │
│  (poll gameflow      │                  (LCU end-of-game stats)                │
│   phase via LCU)     └──► fun prompt popup (native toast/window)               │
│                                                                                │
│  embedded web server ──► dashboard (localhost, charts)                         │
└────────────────────────────────────────────────────────────────────────────────┘
```

### Key technical choices

- **Data source: LCU API (local client), not the Riot web API.**
  The LCU exposes everything needed (gameflow phase, end-of-game stats, match history, lobby members) with **no API key**, no rate limits, no key-expiry hassle. The Riot web API (Match-V5) requires a dev key that expires every 24h — a non-starter for an always-on personal tool. Riot Match-V5 stays as a *future option* for backfilling history (§9).
  ⚠️ The LCU API is unofficial/undocumented; endpoints occasionally change with patches. Mitigation: F4 (store raw payloads), thin adapter layer around LCU calls, community-maintained endpoint docs.

- **Premade detection:** capture the lobby/party members via LCU before the game starts (or from the end-of-game payload's party info) — this is what distinguishes "played *with* Alex" from "Alex happened to be matched with me".

- **Event-driven, not polling:** subscribe to the LCU WebSocket (`OnJsonApiEvent` for gameflow phase changes) instead of polling REST endpoints in a loop. The process sleeps until the client pushes an event — near-zero idle CPU, which is the main "lightweight" lever.

- **Stack (confirmed):** Python.
  - `willump` or plain `httpx` + lockfile parsing for the LCU connection
  - `pystray` + native Windows toast (`windows-toasts`) or a small always-on-top `tkinter`/`webview` popup for the rating
  - `FastAPI` (or Flask) serving a single-page dashboard with `Chart.js`
  - `sqlite3` stdlib for storage
  - Packaged with `pyinstaller` into a single exe later; run via `pythonw` during development.
  Node/Electron would also work but is heavier than needed for a tray tool.

### 6a. Vanguard & Riot compliance (hard constraints)

The tool must stay unambiguously on the safe side of Riot's third-party app policy and give Vanguard nothing to object to. These are **permanent constraints**, not v1 choices — any future feature that would break one of them is rejected:

1. **LCU local REST/WebSocket API only** — the same officially tolerated mechanism used by mainstream companion apps (Blitz, Porofessor, etc.). Standard HTTPS to `127.0.0.1` using the lockfile credentials Riot itself provides for this purpose.
2. **Never touch the game process.** No memory reading, no DLL injection, no hooks, no screen capture of the game.
3. **No in-game presence.** No overlay, and the rating popup is never shown during live gameplay (F10b enforces this). All interaction happens pre-game or post-game.
4. **No input automation.** The tool never sends clicks/keys to the client or game; it only reads data.
5. **No competitive advantage.** Fun ratings and post-game stats provide zero in-match benefit — the safest possible category under Riot's policy.

Net risk assessment: passive post-game LCU reads are what the entire companion-app ecosystem is built on; Vanguard targets cheats that manipulate the game process, which this tool never approaches.

### 6b. Lightweight requirements (NFRs)

| ID | Requirement |
|----|-------------|
| N1 | Idle CPU ≈ 0% — event-driven via LCU WebSocket, no busy polling. |
| N2 | Memory footprint target < 100 MB for the tray process. |
| N3 | No GPU usage outside the dashboard browser tab (which only exists while open). |
| N4 | Dashboard web server binds to localhost only and may start lazily (on first "open dashboard") to keep the resident process minimal. |
| N5 | Single small process; no background services, no drivers, no auto-updater daemon. |

---

## 7. MVP & Phasing

### Phase 1 — Capture loop (the foundation)
Tray app, LCU connection, game-end detection, data capture to SQLite, basic rating popup (1–5, no tags). **Exit criterion:** play 3 games, all 3 recorded and rated with zero manual steps besides the rating click.

### Phase 2 — Insights v1
Dashboard with the global filter bar and explorer view (F13b/F13c), champion kiffance, squad kiffance, context breakdowns (F13–F16, F21), pending-ratings page (F11).

### Phase 3 — Delight
Tags, fun-facts cards, session analysis, trends, remake handling, missed-game recovery (F5, F6, F9, F17–F19). *(Tags/notes done 2026-07-20: dashboard-based — the popup stays one-click; tag/note any game, default tag set seeded and user-editable, "Tags" tab with per-tag fun breakdown.)*
**Popup design pass (TODO from 2026-07-20 testing):** the v1 popup works but looks rough — tkinter renders the emoji as monochrome outlines, not color. Rework the visuals (color emoji via images or a webview-based popup, spacing, hover states) once the capture loop is validated.

### Phase 4 — Share-ready (required before inviting friends)
Single-exe GitHub release, friend-proof README, JSON/CSV export, launch-on-startup option, tag insights. (Riot API backfill stays optional.)

---

## 8. Success Metrics

- **Rating coverage:** ≥ 90% of games get rated (the prompt is frictionless enough that I actually do it).
- **Reliability:** ≥ 95% of games auto-captured with full data.
- **The real test:** after ~30 rated games, the dashboard tells me at least one thing about my fun I didn't already know.

---

## 9. Decisions (resolved 2026-07-20)

| Question | Decision |
|----------|----------|
| Rating scale | **1–5 grade scale**, one click, enough nuance for averages. Grades (set 2026-07-20): 1 **Absolute Skibidi** 🚽 · 2 **Who Let Them Cook?** 🤨 · 3 **Meh** 🧍 · 4 **Let Him Cook!** 👨‍🍳 · 5 **Maximum Rizz** 👑. Emoji render in color (Pillow COLR font). *Future:* swap emoji for actual meme-face icons (Shocked Pikachu → Chad) — needs non-copyright-encumbered art. |
| Prompt style | **Always-on-top popup window** — hard to miss, best rating coverage. |
| Popup vs. next game | **Hides immediately when a new game starts**, game goes to the pending list (F10b). Never visible during gameplay. |
| Game modes | **All modes captured** — Ranked, Normals, ARAM, Arena, ARAM Mayhem, and any future rotating mode (F3b, revised 2026-07-20; supersedes the earlier ranked/normals/ARAM-only decision). Filtering by mode happens in the dashboard, not at capture time. |
| Dashboard filtering | **Fully user-driven** — global filter bar on every view + a free "explorer" (pick your own grouping & chart type). Canned insights are shortcuts, not constraints (F13b/F13c). |
| Tags & notes | **Phase 3** — Phase 1 popup stays a pure one-click rating. |
| UI language | **English** (popup, dashboard, tags). |
| Startup | **Manual launch by default**, opt-in "start with Windows" checkbox in settings (F23). |
| Tech stack | **Python** — tray app + FastAPI dashboard + Chart.js + SQLite. |

| Social model | **Tier 1: GitHub distribution, fully local per player** (see §11). Shared/hosted stats are a future direction, not v1. |
| Compliance | **Vanguard-safe hard constraints** locked in §6a; lightweight NFRs in §6b. |

Still open (non-blocking, revisit post-MVP):
- **Historical backfill** via Riot Match-V5: old games can't be fun-rated from memory reliably — probably no, but the schema (`riot_match_id`) keeps the door open.

---

## 10. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| LCU API changes with a patch | Capture breaks silently | Raw payload storage, adapter layer, startup self-check that logs loudly when an endpoint fails |
| Rating fatigue → skipped prompts | Data gaps, biased stats | One-click UX, auto-pending instead of nagging, "skip" option, pending page |
| Instant re-queue hides the prompt | Missed ratings | Always-on-top popup + 5-min grace + pending page |
| Small sample sizes → misleading insights | Wrong conclusions ("Yasuo is fun" after 2 games) | F21: minimum-games thresholds everywhere |
| Tool not running when a game is played | Missing games | F6 startup catch-up import; launch on startup |

---

## 11. Future: Social

**Decision: v1 ships as Tier 1** — the project lives on GitHub, friends install it, and each player runs their own fully local instance with their own stats. No hosted component, no data leaves anyone's machine.

The social component **matters long-term**: the goal is that friends can see their own little stats too, and eventually the squad's fun data could live together (leaderboards, "fun when we duo" comparisons — including the unique mutual-rating angle where both duo partners rate the same game). That likely means an optional small hosted backend one day. It is deliberately **not** designed now, but v1 must not paint us into a corner:

### Design constraints to honor from day one
1. **Storage behind an interface.** All reads/writes go through a single "game store" layer — never raw SQLite calls scattered through the code. Adding "also sync to a server" later becomes a plug-in, not a rewrite.
2. **PUUID as the player key** (already in the schema): stable across name changes and identical across every friend's database, so datasets can be merged later without migration pain.
3. **Portable data.** Ratings + normalized fields exportable as JSON/CSV from v1 — a manual "compare with a friend" story exists even before any backend, and it's the escape hatch if a backend never happens.
4. **README written for friends, not just for me.** Installation must be doable by a non-dev friend (eventually a single .exe release on GitHub — this upgrades the Phase 4 packaging item from "optional" to "required for social Tier 1").
5. **Any future social feature must still pass §6a** (Vanguard constraints) and §6b (lightweight) — a sync client is a background HTTP push of already-captured data, which fits; anything more invasive doesn't.

---

## 12. Social — Tier 3: shared squad backend (in progress, decided 2026-07-20)

Local capture stays exactly as-is. This adds an **opt-in** layer: log in, join a squad, and your *rated* games sync to a shared backend so the squad can see leaderboards and the mutual-fun matrix. Off by default — a player who never logs in is unaffected and fully local.

### Decisions
| Question | Decision |
|----------|----------|
| Backend | **Supabase** — managed Postgres + built-in Auth + Row-Level Security + auto REST. Free tier covers a squad; near-zero ops. |
| Identity | **Full accounts** via Supabase Auth (email/password). On first sync the app links `auth.uid ↔ PUUID ↔ display name`. |
| Grouping | **Squads** with **invite codes**: one member creates a squad and shares a code; friends paste it to join. |
| Privacy | **Opt-in and squad-scoped.** Only rated, non-skipped games sync. RLS makes a player's shared games visible **only** to members of squads they share. A per-game "don't share" flag is available. |

### Backend schema (Supabase / Postgres)
- `profiles` — `id` (= auth.uid), `puuid`, `display_name`. Maps account ↔ in-game identity.
- `squads` — `id`, `name`, `owner_id`, `created_at`.
- `squad_members` — `squad_id`, `user_id`, `role`, `joined_at`.
- `squad_invites` — `code`, `squad_id`, `created_by`, `expires_at`.
- `shared_games` — one row per player per game: `user_id`, `riot_match_id`, `played_at`, `queue_type`, `champion`, `role`, `win`, `kills/deaths/assists`, `duration_seconds`, `fun_score`, `synced_at`. **`riot_match_id` is the join key** — same value for all players in a game — so two squad members' ratings of the same game line up for the mutual-fun matrix.

RLS: a user reads `shared_games`/`profiles` only for users co-membered in a squad; writes only their own rows. `service_role` key is never shipped; the **anon key is public-by-design** (RLS is the guard) and lives in a gitignored local config, not the repo.

### App changes
| ID | Requirement |
|----|-------------|
| F25 | Opt-in account login (email/password) from a dashboard "Squad" settings page. Sync is disabled until logged in. |
| F26 | Create a squad / join by invite code. |
| F27 | Background sync worker: push the user's rated, non-skipped games to `shared_games` (behind the game-store interface, §11 constraint 1). Async HTTP, honors §6a/§6b. |
| F28 | **Squad leaderboard** — avg fun per member (this week / all-time), with sample sizes (F21). |
| F29 | **Mutual-fun matrix** — for games two members both played (matched on `riot_match_id`), show each pair's two fun scores: "you rated it 4.5, Alex rated it 2.8." |
| F30 | Privacy: sync opt-in; only non-skipped rated games; per-game "don't share"; leaving a squad removes your visibility to it. |

### External dependency
Requires a Supabase project (created by the user — account creation can't be automated). The repo provides the SQL schema/migration to run in Supabase; the app reads the project URL + anon key from a local gitignored config.

---

## 13. Future: richer game analysis (data already captured)

Fun isn't explained by your own champion alone — the enemy team, ARAM Mayhem augments, your build, and mode mutators all shape the game and how it felt. **This data is already being captured**: verified 2026-07-20 that stored `raw_payload`s contain, for all 10 players on both teams, `playerAugment1..6`, `item0..6`, `gameModeMutators`, champLevel, gold, damage breakdowns, and full stats. We simply don't normalize/surface it yet.

Planned analysis dimensions to extract from the retained raw payloads:
- **Enemy composition** — fun vs. specific enemy champions / archetypes faced.
- **Augments** (ARAM Mayhem, Arena) — which augments correlate with fun and with winning.
- **Builds / items** — item paths vs. fun.
- **Mode mutators** — how each rotating-mode modifier affects fun.
- **Deeper personal stats** — damage, gold, multikills, surrender/remake flags vs. fun.

**Enabler (F4 payoff):** because the full raw payload is retained on every game, adding any new dimension is a normalize-and-backfill step — a one-time re-parse populates the new fields for all historical games, with no recapture. New extraction belongs in `capture.py`; new columns go through the game store (§11). No Vanguard/lightweight impact — it's post-hoc analysis of already-stored data (§6a/§6b safe).

---

## 14. Future: desktop-app shell & online distribution (Blitz/u.gg-style)

Target look & feel: a polished native desktop app like Blitz or u.gg, not "a browser tab." Our Phase 2 choice (web dashboard served on localhost) was made partly for this — the frontend is already decoupled HTML/CSS/JS, so shelling it into a native window is additive, not a rewrite.

- **Native window (recommended: `pywebview`)** — wrap the existing dashboard in a frameless native window using the OS Edge WebView2 runtime (no bundled browser → stays within §6b lightweight). Custom title bar/chrome. Electron (what Blitz uses) is the higher-ceiling alternative but adds a full JS/Node stack; adopt only if pywebview proves limiting.
- **Must be a download, not a web app** — the LCU is local to each player's PC, so no website can drive capture. Online = a **landing/download page** + the social backend (§12); the capture app itself is always a local download (this is exactly the Blitz model, and matches the Phase 4 single-exe release).
- **Login is optional** — the summoner name + PUUID come from the local LCU, so a player needs **no account** to use the app and see their own fun stats. Accounts (§12) unlock only the shared/social features. Never gate local use behind login.
- Fits the hard constraints: still LCU-only, still lightweight, still single local process (§6a/§6b).

## 15. Voice & tone — the "lame on purpose" pass

Deliberately corny, over-the-top, affectionate franglais/gamer voice is core to the product's charm — a personal fun-tracker should feel like a friend roasting you, not a stats dashboard. A dedicated copy pass across popup, dashboard labels, fun-facts cards, empty states, and loading messages.

- Direction: cheesy, punny, self-aware. Examples (illustrative, not final): **Kiff-o-meter** (avg fun), **Certified Banger / Certified Yikes** (best/worst champ), **"the 'one more game' regret curve"** (session fatigue), **Copium champions** (winning-but-miserable), loading lines like *"Consulting the vibes…"* / *"Asking your jungler what happened…"*.
- Keep it skimmable and non-annoying (the one-click rating stays instant); tone lives in labels, cards, and flavor text, never in extra friction.
- Consolidate all user-facing strings so the voice is consistent and easy to tune (also eases any future localization, though UI language is English per §9).
