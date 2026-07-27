# Monitoring VibeCheck

How to see how many people use the app, how much they play, and which version
they're on — without hosting anything.

Everything lives in **Supabase Studio**, behind your existing login. There is no
separate dashboard to deploy and no `service_role` key anywhere: that key must
never leave Supabase, which is precisely why the maintainer view stays there.

## One-time setup

1. **Create the telemetry table.** Supabase → SQL Editor → New query → paste
   [`supabase/telemetry.sql`](../supabase/telemetry.sql) → Run.
   It's additive and safe to re-run.

   > It is a separate file from `schema.sql` on purpose. That one *drops* tables
   > so it can be re-run; putting telemetry there would wipe every ping the
   > first time you re-applied the schema.

2. **Save the queries.** Open [`supabase/monitoring.sql`](../supabase/monitoring.sql)
   and paste each block into the SQL Editor, then **Save query** with a name
   (`headline`, `growth`, `version spread`, …). One click to re-run afterwards.

3. **Optional — build a Reports page.** Supabase → **Reports** → *New custom
   report* → add a **SQL block** per query and pick a chart type. Drag to
   arrange. That's your dashboard: charted, refreshed on open, private to you.

## What each query answers

| Query | Answers |
|---|---|
| **headline** | Users, rated games, average vibe, 7-day actives |
| **growth** | New users per day — Reddit spikes show up here |
| **vibe distribution** | Is anyone clicking FF at 15, or is everything a 3? |
| **version spread** | Who is still on an old build? Run before and after every release |
| **install funnel** | Installs vs. installs that ever rated — a big gap means people never reach the popup |
| **daily actives** | Installs pinging per day |
| **retention** | Of installs 7+ days old, how many are still around? |

## Two sources, two blind spots

- **`shared_games`** — real usage, but only from people who *rate* games and
  have the backend reachable. Nothing about version or install count.
- **`telemetry_pings`** — one row per install per day: version, OS, and a few
  counts. Covers people who never rate anything. Nothing about *which* games.

Neither contains summoner names, PUUIDs, or match ids, so neither can tell you
who someone is. That's by design.

## Is Supabase itself healthy?

Already covered natively — no work needed:

- **Reports → API** — request volume and error rate
- **Reports → Database** — size and connection count against the free-tier ceiling
- **Authentication → Users** — anonymous sessions being created
- **Logs** — recent errors

## ⚠️ The one rule

**Never `grant select` on these tables or any view over them to `anon`.**

The app ships with the publishable (anon) key, so anything readable by `anon` is
readable by *every copy of VibeCheck in the world*. RLS is what keeps a user's
games visible only to their mutual friends, and what keeps `telemetry_pings`
write-only for clients. Studio bypasses RLS as table owner — that's the intended
and only path for these queries.

## Turning telemetry off (as a user)

Profile menu → **Anonymous usage stats**. When off, the app makes no telemetry
network calls at all. It's on by default and documented in the README's Privacy
section, which is what keeps on-by-default honest.
