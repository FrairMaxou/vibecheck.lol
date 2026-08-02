# Security

The pre-deployment security review, and the reasoning behind each answer.

Run the checklist at the bottom before every release, alongside
[docs/RELEASE.md](RELEASE.md). Most of it is automated — `tests/security_test.py`
fails CI if a guard is removed — but the items marked **manual** live in the
Supabase console and no test here can see them.

## What the attack surface actually is

VibeCheck is a desktop app, not a web service, and that changes which of the
standard web risks apply. There are exactly three places untrusted input or
untrusted callers meet our code:

| Surface | Who can reach it | What protects it |
|---|---|---|
| The localhost dashboard (`127.0.0.1:8577`) | Any program on this PC, **and any web page the user has open** | Trusted-host + CSRF guard + CSP ([vibecheck/security.py](../vibecheck/security.py)) |
| Supabase (squad sync, telemetry) | Anyone — the publishable key ships in the app | Row-Level Security ([supabase/schema.sql](../supabase/schema.sql)) |
| The LCU and Data Dragon payloads | Riot, plus whatever other players typed as their name | Defensive parsing ([capture.py](../vibecheck/capture.py)), escaping on render |

The third one is easy to miss: a summoner name in a match payload is text written
by a stranger that ends up in our HTML.

There is **no public web frontend and no server we operate** — which is why
several rows below read "not applicable" rather than "done".

## The checklist, answered

### Rate limiting — partial, and deliberately so

The dashboard has none and doesn't need it: it serves one local user, and a
flood from this machine is a flood the user is causing themselves. What matters
is the calls that leave the machine, and those are budgeted:

- GitHub release checks are cached for 6h and shared between the tray check and
  the dashboard, against an unauthenticated limit of 60 req/h
  ([updater.py](../vibecheck/updater.py)).
- Telemetry sends at most one row per install per day, enforced by the primary
  key — a second ping the same day is a 409 the client treats as success.

**Manual:** Supabase's own rate limits are project settings, not code. Confirm
they're on — the publishable key is public, so identity-farming is the one abuse
path that costs real quota.

Verified 2026-08-02, all at Supabase defaults. Only the first line matters:
anonymous sign-in is this app's entire auth path.

| Limit | Value | Why it's fine |
|---|---|---|
| Anonymous users | 30/h per IP | An install signs in **once**, then refreshes. Biting this needs 30 fresh installs behind one NAT in an hour, and the failure is a graceful `SupabaseError` retried on the next rating |
| Token refreshes | 150/5min (1800/h) per IP | We refresh hourly |
| Sign-ups/sign-ins | 30/5min per IP | Excludes anonymous users — we never use email/password, so this never applies |
| Emails / SMS / Web3 | 2/h, 30/h, 30/5min | We send none of these |

Treat a *lowered* anonymous limit as the drift to watch for: it would start
failing real installs, and the symptom (squad sync quietly not working for new
users) looks nothing like a rate limit.

This one genuinely cannot be automated from a dev machine, and it's worth
knowing *why*: rate limits live on the Management API, which only accepts a
personal access token (`sbp_…`). The publishable key the app ships is rejected
there with `401 JWT could not be decoded` — as it should be. Nothing the build
has access to can read this, by design.

The fastest check is the console — Auth → Rate Limits on the project. Don't go
looking for the Supabase CLI to do it: it isn't on winget, and there's no
scoop/choco/npm on the maintainer's machine to install it with, so reaching for
it means installing a package manager to fetch a tool whose only job here is to
hold a token. If you want it scriptable instead, mint a personal access token
(Dashboard → Account → Access Tokens), keep it in your environment, and skip the
CLI entirely:

```bash
curl -s -H "Authorization: Bearer $SUPABASE_ACCESS_TOKEN" \
  "https://api.supabase.com/v1/projects/<project-ref>/config/auth" | grep -i rate_limit
```

What the publishable key *can* confirm, no token needed — useful because squad
sync silently does nothing if anonymous sign-ins ever get turned off:

```bash
curl -s -H "apikey: <publishable-key>" "https://<project-ref>.supabase.co/auth/v1/settings"
# -> "anonymous_users": true, "disable_signup": false
```

### API keys and secrets — no secret ever ships

The app ships **only** the Supabase publishable (anon) key, which is designed to
be embedded in clients. Data is protected by RLS, not by that key being hidden.
The `service_role`/secret key is never shipped, committed, or used by this app —
it exists only in Supabase Studio, which is also the only place the monitoring
queries in [supabase/monitoring.sql](../supabase/monitoring.sql) are ever run.

The publishable key is still kept out of the repo (`vibecheck/_bundled.py` is
gitignored, injected from a GitHub secret at release time) — not because it's
secret, but so scrapers don't find the endpoint and burn the free tier.

### Row-Level Security — on, on all four tables

`profiles`, `friend_links`, `shared_games`, `telemetry_pings` all have
`enable row level security`, and every policy is scoped to the caller:

- reads: your own rows, plus rows belonging to a **mutual** friend (`is_mutual()`)
- writes: only rows whose `puuid` is yours (`my_puuid()`), only edges you own
- `telemetry_pings` has an **insert policy and nothing else** — with RLS on, the
  absence of a select policy means no client can read that table at all, its own
  rows included.

Both helpers are `security definer` with a pinned `search_path`, which is what
lets them read those tables from inside a policy without recursing on it.

Because anyone can *claim* a PUUID, this is soft security by design (PRD §12):
the thing being protected is how much fun someone had. That trade-off is a
locked decision — but it is the reason **nothing sensitive may ever be added to
these tables**. Adding a field that actually matters would invalidate the model,
not just the schema.

### Environment variables and secrets in the repo — clean

`.gitignore` covers `.claude/` and `vibecheck/_bundled.py`; the `gitleaks`
pre-commit hook scans every commit; `git log --all` shows no credential file was
ever committed. The one place a real secret exists is GitHub Actions
(`secrets.SUPABASE_*`), consumed at build time and never written to a tracked
file.

### Validating and sanitizing input — yes, at both ends

- **Into the database:** Pydantic models bound every request body (tag count and
  label length, note length, rating range, backend URL scheme). Anything the
  LCU sends goes through [capture.py](../vibecheck/capture.py), which never
  trusts a payload's shape and always keeps the raw JSON alongside.
- **Out to the page:** every value that didn't come from our own arithmetic is
  escaped before it enters an HTML string (`escapeAttr` in `web/app.js`).
  Champion names, teammate names, tags, notes and backend error strings all go
  through it. The CSP is the second line, not the first.

### Public-by-default tables — none, but read *why* carefully

No table is readable by an unauthorised caller. `telemetry_pings` is the closest
thing to an exception — anonymous clients may insert — and even there they can
never read back a single row, their own included.

But the reason matters more than the verdict. It is tempting to write "every
table denies by default"; that is **false**, and believing it is how the next
table gets shipped open. Verified against production on 2026-08-02, all four
tables carry `DELETE, INSERT, REFERENCES, SELECT, TRIGGER, TRUNCATE, UPDATE` to
anon/public. That is Supabase's default: it grants broadly and expects RLS to do
the filtering. It is not exploitable — `anon` has no `BYPASSRLS`, so policies
still apply, and PostgREST never issues `TRUNCATE` — but it means:

> **RLS is a single point of failure.** A new table in `public` without
> `enable row level security` is instantly world-readable *and world-writable*
> by every copy of the app, because the grants are already there waiting.

Hence the RLS line in `verify-security.sql` is the highest-value check in this
document, and hence the checklist item about new tables.

Two standing rules:

1. **Never `grant select` to `anon`** on any view over these tables. Views do
   not inherit RLS from their tables, so one such grant hands the entire global
   dataset to every copy of VibeCheck. (Verified clean: every grant row reports
   `[table]`, none `[view]`.)
2. **A grant is not a defence, and RLS is not a grant.**
   [supabase/harden-grants.sql](../supabase/harden-grants.sql) narrows this to
   what the app actually uses — `anon` keeps `INSERT` on `telemetry_pings` and
   nothing else, and `TRUNCATE`/`TRIGGER`/`REFERENCES` go everywhere (no REST
   client can issue them, and `TRUNCATE` is the one privilege here that RLS does
   *not* filter). After it, an accidental select policy on `telemetry_pings`
   still reads nothing, because the grant is gone too.

### Authentication on protected routes — by design, not by password

The dashboard has no login, and shouldn't: it binds to `127.0.0.1` and shows one
user their own local SQLite file. There is no account system to authenticate
against and nothing to gate. The real question — *can something else reach it?*
— is answered by the three browser guards, not by auth.

On the backend, the anonymous Supabase session **is** the authentication: RLS
policies key off `auth.uid()`, so an unauthenticated caller sees nothing.

### Error messages and stack traces — nothing leaks

FastAPI returns a bare `Internal Server Error` for unhandled exceptions;
tracebacks go to the log file in the app's data folder (`config.LOG_PATH`), on
the user's own machine. Backend errors are passed through as readable text (a Supabase
message, not a trace) and are escaped before rendering.

### Admin and debug endpoints — off

`docs_url`, `redoc_url` and `openapi_url` are all `None`, so the interactive
docs that enumerate every route don't exist. `/static/` and `/assets/` serve
from a fixed allowlist, so no path traversal is possible regardless of what the
URL says. Everything under `tools/` is a maintainer script that runs by hand and
ships in no build.

### Broken access control — the server decides, never the client

The client never says which rows it may see. `friends_games()` issues an
*unfiltered* select and lets RLS do the filtering — so a tampered client asking
for everything gets back exactly its own rows plus its mutuals'. Ownership is
proved by `auth.uid()` (a session the caller cannot forge), never by a PUUID in
the request.

Locally there is no access control question: one user, one machine, their own
database.

### SQL injection — parameterized everywhere, and structurally contained

Every SQLite call in [store.py](../vibecheck/store.py) uses `?` placeholders —
no f-string ever carries a value into SQL. The two `# noqa: S608` suppressions
are both structural, not data: a column name from a fixed tuple in the migration,
and a run of `?` placeholders generated from a list's *length*.

PostgREST is not string SQL at all — filters are sent as typed query parameters,
so `eq.{puuid}` is a value, never a fragment.

This holds because of the PRD §11 constraint: `store.py` is the only module that
may touch SQLite. Feature code has no way to write a query, so there is nowhere
else for an injection to hide.

### Public key in the frontend, admin key server-side — yes

The only key that reaches a user's machine is the publishable one. There is no
"admin key server side" because there is no server of ours: privileged access
means opening Supabase Studio and logging in.

## Before every release

Run this alongside the [release checklist](RELEASE.md).

```powershell
.venv\Scripts\python tests\security_test.py
.venv\Scripts\ruff check .
.venv\Scripts\pip-audit -r requirements.txt
```

- [ ] `tests\security_test.py` passes (CSRF guard, CSP, host check, allowlists, input bounds)
- [ ] `ruff check .` clean — the `S` (bandit) ruleset is on, and `S501`/`S608`
      are the only allowed suppressions, each with a comment saying why
- [ ] `pip-audit` clean, or every finding triaged in the PR
- [ ] no real key value in the repo — this matches key *shapes*, not the words
      (grepping for `service_role` alone hits ten lines of prose and trains you
      to ignore the check):

      ```
      git grep -nE "sb_secret_[A-Za-z0-9_-]{10,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"
      ```
- [ ] the built exe's `vibecheck/_bundled.py` holds the **publishable** key —
      `tools/bake_credentials.py` refuses a secret key, so check it ran
- [ ] no new HTML string in `web/app.js` interpolates a value without
      `escapeAttr` — grep the diff for `` `${ `` inside `innerHTML`
- [ ] no new inline `on*=` handler in `web/` (the CSP blocks it; the test catches it)
- [ ] any new endpoint that changes state is a `POST` and was considered against
      the CSRF guard — a bodyless POST is reachable cross-site if the guard is
      bypassed, so add it to `BODYLESS_WRITES` in the test
- [ ] any new Supabase table has `enable row level security` **plus** a policy;
      RLS with no policy denies everything, which is safe but silently broken
- [ ] no new field on a synced table carries anything more sensitive than a
      fun score — the soft-identity model can't protect it
- [ ] **manual:** Supabase Studio → SQL Editor →
      [supabase/verify-security.sql](../supabase/verify-security.sql). Read-only;
      it reports RLS state, every policy, every `anon` grant, and row counts, so
      drift between `schema.sql` and the live project is visible rather than
      assumed. Covers the "no view granted to `anon`" check
- [ ] **manual:** Supabase → Auth → rate limits still enabled (baseline above)

## Running SQL against production

Integrity counts as a security property, and the fastest way to lose data here
isn't an attacker — it's pasting the wrong file into the SQL editor. The files
in `supabase/` are not interchangeable:

| File | Destructive? | When to run |
|---|---|---|
| `verify-security.sql` | No — single SELECT | Every release, and any time you want the truth about prod |
| `monitoring.sql` | No — SELECTs | Whenever |
| `harden-grants.sql` | REVOKE only — no data, no schema | Once; re-runnable and reversible |
| `fix-profiles-puuid-unique.sql` | Drops a constraint, deletes orphan rows | Once, on a project carrying the old constraint |
| `schema.sql` | **DDL.** Rebuilds tables and every policy | A fresh project, or to refresh policies |
| `telemetry.sql` | Creates only | Once, on a fresh project |

Two rules, both learned the expensive way on 2026-08-02, when `schema.sql` was
run on prod to check the policies and silently emptied `shared_games`:

1. **A "safe to re-run" comment is not a guarantee — the SQL is.** That file
   said it was safe to re-run *and* that it dropped shared game rows, in the
   same sentence, which read as reassurance. It now refuses to drop a
   `shared_games` that has rows.
2. **Read-only checks belong in their own file**, so "run this to look at
   something" never means opening the file that rebuilds the schema.

If a destructive run does happen, `shared_games` is the one table that
self-heals: `push()` upserts a client's entire rated history rather than a
delta, so every user restores their own rows on their next rating, and the local
SQLite database — the actual source of truth — is never involved.

## Known and accepted

- **Anyone can claim a PUUID.** Identity is soft by design (PRD §12). The cost
  is a stranger seeing fun scores; the benefit is zero-config squads.
- **Anyone can post junk telemetry rows.** The publishable key ships in the app.
  This is a hobby metric, not billing data — a wrong count is the whole cost.
- **The exe is unsigned.** Windows SmartScreen warns on first run. Self-update
  is protected instead by a host allowlist on every redirect hop and a SHA-256
  check against the published checksums — a build that can't be verified is
  never installed.
- **Local data is unencrypted.** The SQLite database sits in `%LOCALAPPDATA%`
  under the user's own account. Encrypting it would mean shipping the key next
  to it, which protects nobody.
