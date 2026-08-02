-- VibeCheck.lol — verify the DEPLOYED security posture. READ-ONLY.
--
-- Run this in Supabase Studio → SQL Editor before every release (it is a line
-- in docs/SECURITY.md's checklist). It creates nothing, drops nothing, and
-- writes nothing — the whole file is a single SELECT.
--
-- Why it exists: everything the security review claims about RLS comes from
-- reading supabase/schema.sql, which is what *should* be deployed. This shows
-- what actually IS, so drift between the file and the project is visible
-- instead of assumed.
--
-- ⚠️ Do not confuse this file with schema.sql. That one is DDL and rebuilds the
-- schema; this one only looks. If a run of this file reports "Success. No rows
-- returned", you ran something else — this query cannot return zero rows on a
-- live project.
--
-- What to look for in the output:
--   * any '*** RLS DISABLED ***'  — that table is readable by every copy of the
--     app, since the publishable key ships inside it
--   * any GRANT row marked [view] — views do NOT inherit RLS from their tables,
--     so one granted to anon over shared_games or telemetry_pings hands the
--     global dataset to everyone. This is the most dangerous thing that can be
--     added to this project by accident
--   * SELECT granted on telemetry_pings — it must stay insert-only
--   * a 'profiles_puuid_key' row — not security, but it permanently breaks
--     squad sync for any player whose anonymous session is recreated
--     (fix: supabase/fix-profiles-puuid-unique.sql)

with counts as (
  select 1 as ord, 'row count'::text as check_type, t.name::text as object_name,
         t.n::text as detail
  from (
    select 'shared_games'    as name, (select count(*) from shared_games)    as n
    union all select 'profiles',      (select count(*) from profiles)
    union all select 'friend_links',  (select count(*) from friend_links)
    union all select 'telemetry_pings', (select count(*) from telemetry_pings)
  ) t
),
rls as (
  select 2, 'RLS'::text, c.relname::text,
         case when c.relrowsecurity then 'enabled'
              else '*** RLS DISABLED ***' end::text
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'public' and c.relkind = 'r'
),
pol as (
  select 3, 'policy'::text, (tablename || ' / ' || policyname)::text,
         (cmd || ' to {' || array_to_string(roles, ',') || '}'
          || ' using: '  || coalesce(left(qual, 80), '-')
          || ' check: '  || coalesce(left(with_check, 80), '-'))::text
  from pg_policies where schemaname = 'public'
),
grants as (
  -- relkind 'v'/'m' here is the red flag: a view granted to anon bypasses RLS.
  --
  -- The grantee is part of the output on purpose. An earlier version of this
  -- file grouped it away, which made the result unactionable: the app's data
  -- calls run as `authenticated` (an anonymous sign-in still issues an
  -- authenticated JWT) while telemetry runs as `anon`, so "revoke the extra
  -- privileges" is only safe once you can see which role holds what.
  select 4, ('GRANT to ' || g.grantee)::text,
         (g.table_name || case c.relkind when 'v' then ' [view]'
                                          when 'm' then ' [matview]'
                                          else ' [table]' end)::text,
         string_agg(distinct g.privilege_type, ', ')::text
  from information_schema.role_table_grants g
  join pg_class c on c.relname = g.table_name
  join pg_namespace n on n.oid = c.relnamespace and n.nspname = g.table_schema
  where g.grantee in ('anon', 'authenticated', 'public') and g.table_schema = 'public'
  group by g.grantee, g.table_name, c.relkind
),
leftover as (
  select 5, 'leftover constraint'::text, conname::text,
         'breaks sync on re-auth — run fix-profiles-puuid-unique.sql'::text
  from pg_constraint where conname = 'profiles_puuid_key'
)
select check_type, object_name, detail
from (
  select * from counts
  union all select * from rls
  union all select * from pol
  union all select * from grants
  union all select * from leftover
) t
order by ord, object_name;
