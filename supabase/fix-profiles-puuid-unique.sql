-- Fix: drop the leftover UNIQUE constraint on profiles.puuid.
--
-- Run this once in your Supabase project: SQL Editor → New query → paste → Run.
-- Safe to re-run, and safe on a project that never had the constraint.
--
-- Why
-- ---
-- schema.sql documents that profiles.puuid is intentionally NOT unique: a player
-- legitimately owns a new row whenever their anonymous session is recreated, and
-- my_puuid() only ever reads the caller's own row (`where id = auth.uid()`).
--
-- Projects created before that was settled still carry a `profiles_puuid_key`
-- unique constraint, and `create table if not exists` never removes it. On those
-- projects the first re-authentication breaks squad sync *permanently* for that
-- player: the new session's profile insert collides with their old row, and RLS
-- (write only where id = auth.uid()) stops the client from clearing it.
--
-- This file is separate from schema.sql on purpose — schema.sql drops tables so
-- it can be re-run, so it must never be the place a live fix lives.

alter table profiles drop constraint if exists profiles_puuid_key;

-- Optional tidy-up: remove profile rows whose auth user no longer exists.
-- Harmless to skip; they are invisible to clients either way.
delete from profiles p
where not exists (select 1 from auth.users u where u.id = p.id);
