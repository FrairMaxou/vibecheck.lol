-- VibeCheck.lol — narrow the table grants to what the app actually uses.
--
-- Run once in Supabase Studio → SQL Editor. Safe to re-run. Reversible (see the
-- bottom). It changes no data and drops nothing — REVOKE only.
--
-- Why
-- ---
-- Supabase grants every privilege on every public table to `anon` and
-- `authenticated` by default and relies entirely on RLS to filter rows. That
-- works, but it makes RLS a single point of failure: a table added without
-- `enable row level security` is world-readable AND world-writable the moment it
-- exists, because the grants are already sitting there. Verified on prod
-- 2026-08-02 — all four tables carried DELETE, INSERT, REFERENCES, SELECT,
-- TRIGGER, TRUNCATE, UPDATE for both roles.
--
-- This does not fix that (default privileges are Supabase's, not ours). It
-- removes the privileges no caller can legitimately use, so the blast radius of
-- an RLS mistake is smaller and `telemetry_pings` stops depending on RLS alone.
--
-- What the app actually needs, traced through vibecheck/sync.py and telemetry.py:
--   authenticated  -> SELECT, INSERT, UPDATE, DELETE on profiles, friend_links,
--                     shared_games. An anonymous Supabase sign-in still issues an
--                     *authenticated* JWT, so this is the role all squad sync
--                     runs as. Do not revoke these: it breaks sync for everyone.
--   anon           -> INSERT on telemetry_pings, and nothing else anywhere.
--                     telemetry.py deliberately sends with the publishable key
--                     and no session, so that installs which never rate a game
--                     still get counted.

-- ---------------------------------------------------------------------------
-- 1. Privileges no REST client can use. PostgREST issues SELECT/INSERT/UPDATE/
--    DELETE and function calls — never TRUNCATE, TRIGGER or REFERENCES. TRUNCATE
--    is the one worth caring about: unlike DELETE it is NOT filtered by RLS, so
--    it is the single privilege here that could empty a table outright.
-- ---------------------------------------------------------------------------
revoke truncate, trigger, references
  on all tables in schema public
  from anon, authenticated;

-- ---------------------------------------------------------------------------
-- 2. telemetry_pings: insert-only for anon, nothing for authenticated.
--
--    Today this table is protected by the *absence* of a select policy — RLS
--    with no policy denies. That is one accidental `create policy` away from
--    publishing the global dataset to every copy of the app. After this, such a
--    mistake still reads nothing, because the grant is gone too.
--
--    Revoking from `authenticated` breaks nothing: tp_insert is declared
--    `to anon`, so an authenticated caller was already denied by policy.
--
--    ⚠️ This couples the ping to one header. telemetry.py sends
--    `Prefer: return=minimal`, so PostgREST inserts without reading the row
--    back. Switch it to `return=representation` and the insert starts needing
--    SELECT — which no longer exists — and every ping fails with a permission
--    error instead of anything obvious. Same applies to the upserts in sync.py
--    if those tables are ever narrowed the same way.
-- ---------------------------------------------------------------------------
revoke all on telemetry_pings from authenticated;
revoke select, update, delete on telemetry_pings from anon;

-- ---------------------------------------------------------------------------
-- Deliberately NOT done: revoking `anon` on profiles / friend_links /
-- shared_games. Those calls always run authenticated, so anon looks removable —
-- but RLS already returns zero rows for it (my_puuid() is null without a
-- session), so the gain is nil, while a path that falls back to the publishable
-- key would turn a harmless empty result into a hard failure. Not worth it on a
-- live database.
--
-- To undo everything above:
--   grant all on all tables in schema public to anon, authenticated;
-- ---------------------------------------------------------------------------

-- Result: anon should hold INSERT on telemetry_pings only; authenticated should
-- hold SELECT/INSERT/UPDATE/DELETE on the three squad tables and nothing on
-- telemetry_pings.
select g.grantee, g.table_name,
       string_agg(distinct g.privilege_type, ', ' order by g.privilege_type) as privileges
from information_schema.role_table_grants g
where g.table_schema = 'public'
  and g.grantee in ('anon', 'authenticated', 'public')
group by g.grantee, g.table_name
order by g.table_name, g.grantee;
