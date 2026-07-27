-- VibeCheck.lol — maintainer monitoring queries.
--
-- Paste these into Supabase Studio → SQL Editor and save each one, or build a
-- Reports page from them (see docs/MONITORING.md). They are kept here so the
-- dashboard is reproducible instead of living only in a browser tab.
--
-- ⚠️ RUN THESE IN STUDIO ONLY. Studio queries run as the table owner and bypass
-- RLS, which is exactly what makes them work. NEVER create a view over these
-- and `grant select` on it to `anon`: the app ships with the anon key, so that
-- would hand the entire global dataset to every copy of VibeCheck.
--
-- Two different sources, answering different questions:
--   shared_games   — real usage, but only from people who RATE games
--   telemetry_pings — install counts and version spread, including people who
--                     never rate anything (see telemetry.sql)


-- ============================================================ headline numbers
-- The "how is it going" query. Start here.
select
  count(distinct puuid)                                            as users,
  count(*)                                                         as rated_games,
  round(avg(fun_score)::numeric, 2)                                as avg_vibe,
  count(*) filter (where synced_at > now() - interval '7 days')     as games_last_7d,
  count(distinct puuid) filter (where synced_at > now() - interval '7 days') as active_users_7d
from shared_games;


-- ==================================================================== growth
-- New users per day — the Reddit-post spike shows up here.
select date(first_seen) as day, count(*) as new_users
from (select puuid, min(synced_at) as first_seen from shared_games group by puuid) t
group by 1
order by 1 desc;


-- ======================================================== vibe distribution
-- Is anyone actually clicking FF at 15, or is everything a 3?
select
  fun_score,
  count(*)                                                as games,
  round(100.0 * count(*) / sum(count(*)) over (), 1)      as pct
from shared_games
group by 1
order by 1;


-- ========================================================== version spread
-- THE query to run before and after a release: who is still on an old build?
-- Pings are one-per-install-per-day, so this counts distinct installs.
select
  app_version,
  count(distinct install_id) as installs,
  max(day)                   as last_seen
from telemetry_pings
where day > current_date - 7
group by 1
order by 1 desc;


-- =========================================================== install funnel
-- How many installs exist, and how many actually rate anything? A big gap
-- means people install it and never get to the rating popup.
select
  count(distinct install_id)                                            as installs,
  count(distinct install_id) filter (where games_rated > 0)             as installs_that_rated,
  count(distinct install_id) filter (where squad_enabled)               as with_backend,
  round(avg(games_captured) filter (where games_captured > 0), 1)       as avg_games_captured
from telemetry_pings
where day > current_date - 30;


-- ============================================================ daily actives
-- Installs pinging per day — the closest thing to a DAU line.
select day, count(distinct install_id) as active_installs
from telemetry_pings
group by 1
order by 1 desc
limit 30;


-- ================================================================ retention
-- Of installs first seen 7+ days ago, how many pinged in the last 7 days?
with cohort as (
  select install_id, min(first_seen) as joined, max(day) as last_day
  from telemetry_pings
  group by install_id
)
select
  count(*)                                                        as installs_7d_plus,
  count(*) filter (where last_day > current_date - 7)              as still_active,
  round(100.0 * count(*) filter (where last_day > current_date - 7) / nullif(count(*), 0), 1) as retention_pct
from cohort
where joined < current_date - 7;
