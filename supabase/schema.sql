-- League of Kiffance — shared squad backend (PRD §12, Tier 3).
--
-- Run this once in your Supabase project: SQL Editor → New query → paste → Run.
-- It creates the tables, helper functions, and Row-Level Security (RLS) policies
-- that make a player's shared games visible ONLY to members of squads they share.
--
-- Auth is Supabase's built-in email/password (auth.users). No passwords live here.

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

-- Maps a login account to its in-game identity (PUUID) + display name.
create table if not exists profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  puuid        text unique,
  display_name text,
  updated_at   timestamptz not null default now()
);

create table if not exists squads (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  owner_id   uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now()
);

create table if not exists squad_members (
  squad_id  uuid references squads (id) on delete cascade,
  user_id   uuid references auth.users (id) on delete cascade,
  role      text not null default 'member',
  joined_at timestamptz not null default now(),
  primary key (squad_id, user_id)
);

create table if not exists squad_invites (
  code       text primary key,
  squad_id   uuid not null references squads (id) on delete cascade,
  created_by uuid not null references auth.users (id) on delete cascade,
  expires_at timestamptz
);

-- One row per player per game. riot_match_id is identical for everyone who was
-- in that game, so two members' ratings of the same game join on it (the
-- mutual-fun matrix, F29).
create table if not exists shared_games (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references auth.users (id) on delete cascade,
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
  unique (user_id, riot_match_id)
);

-- ---------------------------------------------------------------------------
-- Helper functions (SECURITY DEFINER: run with owner rights so RLS policies
-- can reference squad membership without recursing on their own tables).
-- ---------------------------------------------------------------------------

create or replace function is_squad_member(sq uuid)
returns boolean language sql security definer stable set search_path = public as $$
  select exists (
    select 1 from squad_members where squad_id = sq and user_id = auth.uid()
  );
$$;

create or replace function shares_squad_with(target uuid)
returns boolean language sql security definer stable set search_path = public as $$
  select exists (
    select 1
    from squad_members m1
    join squad_members m2 on m1.squad_id = m2.squad_id
    where m1.user_id = auth.uid() and m2.user_id = target
  );
$$;

-- Join a squad by invite code (validates + inserts membership atomically).
create or replace function join_squad(invite_code text)
returns uuid language plpgsql security definer set search_path = public as $$
declare sq uuid;
begin
  select squad_id into sq from squad_invites
   where code = invite_code and (expires_at is null or expires_at > now());
  if sq is null then
    raise exception 'invalid or expired invite code';
  end if;
  insert into squad_members (squad_id, user_id) values (sq, auth.uid())
    on conflict do nothing;
  return sq;
end;
$$;

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------

alter table profiles      enable row level security;
alter table squads        enable row level security;
alter table squad_members enable row level security;
alter table squad_invites enable row level security;
alter table shared_games  enable row level security;

-- Every policy is dropped first so this whole file is safe to re-run. Postgres
-- has no "create policy if not exists", and a half-applied run leaves RLS
-- enabled with policies missing — which denies everything on that table.

-- profiles: see your own + squad-mates'; write only your own.
drop policy if exists profiles_select on profiles;
drop policy if exists profiles_insert on profiles;
drop policy if exists profiles_update on profiles;
create policy profiles_select on profiles for select
  using (id = auth.uid() or shares_squad_with(id));
create policy profiles_insert on profiles for insert with check (id = auth.uid());
create policy profiles_update on profiles for update using (id = auth.uid());

-- squads: visible to members + owner; create/manage your own.
drop policy if exists squads_select on squads;
drop policy if exists squads_insert on squads;
drop policy if exists squads_update on squads;
drop policy if exists squads_delete on squads;
create policy squads_select on squads for select
  using (owner_id = auth.uid() or is_squad_member(id));
create policy squads_insert on squads for insert with check (owner_id = auth.uid());
create policy squads_update on squads for update using (owner_id = auth.uid());
create policy squads_delete on squads for delete using (owner_id = auth.uid());

-- squad_members: members see the roster; you may add/remove only yourself
-- (invite validation happens in join_squad()). The update policy exists so
-- PostgREST upserts are permitted, not just plain inserts.
drop policy if exists sm_select on squad_members;
drop policy if exists sm_insert on squad_members;
drop policy if exists sm_update on squad_members;
drop policy if exists sm_delete on squad_members;
create policy sm_select on squad_members for select using (is_squad_member(squad_id));
create policy sm_insert on squad_members for insert with check (user_id = auth.uid());
create policy sm_update on squad_members for update using (user_id = auth.uid());
create policy sm_delete on squad_members for delete using (user_id = auth.uid());

-- invites: squad members can read + create them.
drop policy if exists si_select on squad_invites;
drop policy if exists si_insert on squad_invites;
create policy si_select on squad_invites for select using (is_squad_member(squad_id));
create policy si_insert on squad_invites for insert
  with check (is_squad_member(squad_id) and created_by = auth.uid());

-- shared_games: your own + squad-mates' are readable; write only your own.
drop policy if exists sg_select on shared_games;
drop policy if exists sg_insert on shared_games;
drop policy if exists sg_update on shared_games;
drop policy if exists sg_delete on shared_games;
create policy sg_select on shared_games for select
  using (user_id = auth.uid() or shares_squad_with(user_id));
create policy sg_insert on shared_games for insert with check (user_id = auth.uid());
create policy sg_update on shared_games for update using (user_id = auth.uid());
create policy sg_delete on shared_games for delete using (user_id = auth.uid());
