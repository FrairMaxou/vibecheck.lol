-- VibeCheck.lol — shared squad backend (PRD §12).
--
-- Run this once in your Supabase project: SQL Editor → New query → paste → Run.
-- Also enable anonymous sign-ins: Authentication → Sign In / Providers →
-- "Allow anonymous sign-ins". The app never asks users to make an account.
--
-- The social model is ZERO-CONFIG and account-free:
--   * identity  = the player's in-game PUUID (from the League client)
--   * auth      = a silent Supabase *anonymous* session (no email/password)
--   * squad     = your League friends who ALSO run VibeCheck and list you back
--                 (a mutual friend link — this replaces invite codes entirely)
--
-- Row-Level Security makes a player's shared games visible only to their mutual
-- friends. Because anyone can *claim* a PUUID, this is soft (fun-tool) security,
-- not a hard identity guarantee — the only "secret" is how much fun you had.
--
-- This file is safe to re-run, including against live production. It drops and
-- recreates every policy (Postgres has no "create policy if not exists"), and
-- it will NOT touch a shared_games table that has rows in it — see the guard
-- below.
--
-- It did not always work that way. Until 2026-08-02 this file dropped
-- shared_games unconditionally, and said so in a sentence that read as
-- reassurance ("each client re-syncs on the next rating") rather than as the
-- warning it was. Running it on prod to refresh the policies wiped every user's
-- synced games. That is why the drop is now conditional: the only way to lose
-- that data is to drop the table by hand, deliberately.

-- ---------------------------------------------------------------------------
-- Drop the previous (accounts + squads + invite codes) model.
-- ---------------------------------------------------------------------------
drop table if exists squad_invites cascade;
drop table if exists squad_members cascade;
drop table if exists squads        cascade;
drop function if exists join_squad(text)          cascade;
drop function if exists is_squad_member(uuid)      cascade;
drop function if exists shares_squad_with(uuid)    cascade;
-- shared_games once changed shape (keyed on puuid now), so this file rebuilt it.
-- That rebuild is only ever correct on a table with nothing in it: on a live
-- project it is a silent data wipe, and the `create table if not exists` below
-- gives no hint that it happened. Drop it only while it is empty — on a project
-- with real rows this is a no-op and the rest of the file still runs, which is
-- the case that actually matters (re-running to refresh the policies).
do $$
begin
  if to_regclass('public.shared_games') is null then
    return;  -- fresh project: nothing to protect, `create table` below builds it
  elsif exists (select 1 from shared_games limit 1) then
    raise notice 'shared_games kept: % row(s) present, not dropping it',
                 (select count(*) from shared_games);
  else
    drop table shared_games cascade;
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

-- Maps an anonymous auth session to its in-game identity (PUUID) + display name.
-- Keyed on the auth user id. puuid is intentionally NOT unique: if a client's
-- anonymous session is ever recreated, a new row for the same puuid is harmless
-- (my_puuid() only ever looks up the caller's own current session).
-- NOTE: projects created before this was settled may still carry a leftover
-- `profiles_puuid_key` unique constraint, which `create table if not exists`
-- will not remove — run supabase/fix-profiles-puuid-unique.sql once to drop it.
create table if not exists profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  puuid        text not null,
  display_name text,
  updated_at   timestamptz not null default now()
);
create index if not exists profiles_puuid_idx on profiles (puuid);

-- Directed friend edges: "owner lists friend as a League friend". A squad
-- relationship exists between two players when BOTH edges are present (mutual).
create table if not exists friend_links (
  owner_puuid  text not null,
  friend_puuid text not null,
  updated_at   timestamptz not null default now(),
  primary key (owner_puuid, friend_puuid)
);

-- One row per player per game, keyed on puuid. riot_match_id is identical for
-- everyone who was in that game, so two mutual friends' ratings of the same
-- game join on it (the mutual-kiff matrix, F29).
create table if not exists shared_games (
  puuid            text not null,
  riot_match_id    text not null,
  played_at        timestamptz,
  queue_type       text,
  champion         text,
  role             text,
  win              boolean,
  kills            int,
  deaths           int,
  assists          int,
  duration_seconds int,
  fun_score        int check (fun_score between 1 and 5),
  synced_at        timestamptz not null default now(),
  primary key (puuid, riot_match_id)
);

-- ---------------------------------------------------------------------------
-- Helper functions (SECURITY DEFINER: run with owner rights so RLS policies can
-- reference these tables without recursing on their own policies).
-- ---------------------------------------------------------------------------

-- The caller's own PUUID, via their profile row.
create or replace function my_puuid()
returns text language sql security definer stable set search_path = public as $$
  select puuid from profiles where id = auth.uid() limit 1;
$$;

-- True when the caller and `other` list each other as friends (mutual edge).
create or replace function is_mutual(other text)
returns boolean language sql security definer stable set search_path = public as $$
  select exists (
           select 1 from friend_links
            where owner_puuid = my_puuid() and friend_puuid = other
         )
     and exists (
           select 1 from friend_links
            where owner_puuid = other and friend_puuid = my_puuid()
         );
$$;

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------

alter table profiles     enable row level security;
alter table friend_links enable row level security;
alter table shared_games enable row level security;

-- profiles: read your own + your mutual friends'; write only your own row.
drop policy if exists profiles_select on profiles;
drop policy if exists profiles_insert on profiles;
drop policy if exists profiles_update on profiles;
create policy profiles_select on profiles for select
  using (id = auth.uid() or is_mutual(puuid));
create policy profiles_insert on profiles for insert with check (id = auth.uid());
create policy profiles_update on profiles for update using (id = auth.uid());

-- friend_links: you manage only edges you own. You may also READ edges that
-- point AT you, so is_mutual() can confirm a friend lists you back.
drop policy if exists fl_select on friend_links;
drop policy if exists fl_insert on friend_links;
drop policy if exists fl_update on friend_links;
drop policy if exists fl_delete on friend_links;
create policy fl_select on friend_links for select
  using (owner_puuid = my_puuid() or friend_puuid = my_puuid());
create policy fl_insert on friend_links for insert with check (owner_puuid = my_puuid());
create policy fl_update on friend_links for update using (owner_puuid = my_puuid());
create policy fl_delete on friend_links for delete using (owner_puuid = my_puuid());

-- shared_games: your own + your mutual friends' are readable; write only yours.
drop policy if exists sg_select on shared_games;
drop policy if exists sg_insert on shared_games;
drop policy if exists sg_update on shared_games;
drop policy if exists sg_delete on shared_games;
create policy sg_select on shared_games for select
  using (puuid = my_puuid() or is_mutual(puuid));
create policy sg_insert on shared_games for insert with check (puuid = my_puuid());
create policy sg_update on shared_games for update using (puuid = my_puuid());
create policy sg_delete on shared_games for delete using (puuid = my_puuid());
