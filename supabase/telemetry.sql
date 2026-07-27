-- VibeCheck.lol — anonymous usage telemetry.
--
-- Run this once in your Supabase project: SQL Editor → New query → paste → Run.
--
-- IMPORTANT: this is deliberately a SEPARATE file from schema.sql. That file is
-- destructive by design (it drops shared_games and the old squad tables so it
-- can be re-run safely), so telemetry must never live there — a future schema
-- re-run would silently wipe every ping ever collected. Nothing here drops
-- anything; the file is safe to re-run.
--
-- What this is for: shared_games only tells us about people who *rate* games.
-- It can't answer "how many installs are out there", "who never rated
-- anything", or — the one that matters the day a release breaks — "which
-- version is everyone on". This table closes exactly that gap.
--
-- What it deliberately does NOT contain: PUUIDs, summoner names, match ids,
-- tags, notes. Identity here is a random per-install UUID with no link to any
-- League account. That's the line between telemetry and tracking.

create table if not exists telemetry_pings (
  install_id      uuid    not null,          -- random per install, NOT a PUUID
  day             date    not null default current_date,
  app_version     text,
  os              text,
  first_seen      date,                      -- when this install first pinged
  games_captured  int,
  games_rated     int,
  avg_vibe        numeric(3,2),
  squad_enabled   boolean,
  created_at      timestamptz not null default now(),
  -- One row per install per day. A second ping the same day hits this and
  -- returns 409, which the client treats as "already counted".
  primary key (install_id, day)
);

alter table telemetry_pings enable row level security;

-- Insert-only for anonymous clients. There is deliberately NO select, update or
-- delete policy: a client can write its own ping and can never read anyone's —
-- including its own. With RLS on, "no policy" means "denied", so this is the
-- whole protection. You read this table from the Studio SQL editor, which runs
-- as the table owner and bypasses RLS.
--
-- NEVER add a select policy for anon, and never `grant select` on any view
-- built over this table to anon — either would hand the global dataset to every
-- copy of the app.
drop policy if exists tp_insert on telemetry_pings;
create policy tp_insert on telemetry_pings for insert to anon with check (true);

-- Known and accepted: the publishable key ships inside the app, so anyone can
-- post junk rows here. This is a hobby usage metric, not billing data — the
-- cost of a fake row is a slightly wrong count. Not worth defending against.

create index if not exists telemetry_pings_day_idx on telemetry_pings (day desc);
