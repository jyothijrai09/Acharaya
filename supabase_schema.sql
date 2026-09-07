-- Acharaya / Jyotish — Supabase schema
--
-- Run once against a new Supabase project:
--   Dashboard -> SQL Editor -> New query -> paste -> Run
--
-- Safe to re-run; every statement is idempotent.

create table if not exists public.profiles (
    id              bigint generated always as identity primary key,
    name            text not null,
    full_birth_name text,
    year            integer,
    month           integer,
    day             integer,
    hour            integer,
    minute          integer,
    tz_offset       double precision,
    lat             double precision,
    lon             double precision,
    place           text,
    created_at      timestamptz default now()
);

-- ---------------------------------------------------------------------------
-- Row level security.
--
-- This table holds birth dates, birth TIMES and birth PLACES — directly
-- identifying personal data. Supabase automatically exposes every table in the
-- `public` schema through PostgREST, so without RLS anyone holding the anon
-- key (which ships in client-side code by design) could read every profile.
--
-- RLS is enabled with NO policies attached. That denies all access through the
-- anon and authenticated roles, while the app's own direct Postgres connection
-- is unaffected: it authenticates as the table owner, and owners bypass RLS.
--
-- If multi-user auth is added later (see "Known gaps" in CLAUDE.md), add a
-- user_id column and a policy of the form
--     using (auth.uid() = user_id)
-- rather than disabling RLS.
-- ---------------------------------------------------------------------------
alter table public.profiles enable row level security;

-- Belt and braces: revoke the grants PostgREST relies on, so the table is not
-- reachable through the REST API even if a permissive policy is added by
-- accident later.
revoke all on public.profiles from anon, authenticated;

comment on table public.profiles is
    'Birth profiles for chart computation. Personal data: RLS on, no policies, no REST access. Reached only by the app''s direct Postgres connection.';


-- ---------------------------------------------------------------------------
-- Readings: the querent's own record of what was asked and what was answered.
--
-- Separate from the conversation history the model is sent. History gives the
-- model continuity within a session; this is the durable record, and it stores
-- what was said rather than the chart block that produced it.
--
-- provider and model are recorded per reading because they can change between
-- questions (LLM_PROVIDER is an environment variable), and a reading is not
-- comparable with another produced by a different model.
-- ---------------------------------------------------------------------------
create table if not exists public.readings (
    id          bigint generated always as identity primary key,
    profile_id  bigint not null references public.profiles(id) on delete cascade,
    persona     text,
    question    text not null,
    answer      text not null,
    provider    text,
    model       text,
    created_at  timestamptz default now()
);

create index if not exists readings_profile_idx
    on public.readings (profile_id, id desc);

-- Same reasoning as profiles: a reading quotes the birth chart and the
-- querent's private questions, so it must not be reachable through the anon
-- key. RLS on, no policies, PostgREST grants revoked.
alter table public.readings enable row level security;
revoke all on public.readings from anon, authenticated;

comment on table public.readings is
    'Questions asked and answers given, per chart. Personal data: RLS on, no policies, no REST access.';
