-- Run this in Supabase SQL editor.
-- Creates license tables for one-device activation with server-side validation.

create extension if not exists pgcrypto;

create table if not exists public.licenses (
  id uuid primary key default gen_random_uuid(),
  app_id text not null,
  license_key_hash text not null unique,
  license_type text not null check (license_type in ('trial', 'full')),
  status text not null default 'active' check (status in ('active', 'revoked')),
  expires_at timestamptz null,
  max_devices int not null default 1,
  created_at timestamptz not null default now()
);

-- Existing table migration safety.
alter table public.licenses add column if not exists license_key_hash text;
alter table public.licenses add column if not exists license_type text;
alter table public.licenses add column if not exists status text;
alter table public.licenses add column if not exists expires_at timestamptz;
alter table public.licenses add column if not exists max_devices int;
alter table public.licenses add column if not exists created_at timestamptz;
alter table public.licenses add column if not exists app_id text;

update public.licenses set status = 'active' where status is null;
update public.licenses set max_devices = 1 where max_devices is null;
update public.licenses set created_at = now() where created_at is null;
update public.licenses set app_id = 'SWOT' where app_id is null;

alter table public.licenses alter column app_id set not null;
alter table public.licenses alter column status set not null;
alter table public.licenses alter column max_devices set not null;
alter table public.licenses alter column created_at set not null;

alter table public.licenses alter column status set default 'active';
alter table public.licenses alter column max_devices set default 1;
alter table public.licenses alter column created_at set default now();

create index if not exists idx_licenses_app_id on public.licenses(app_id);

create table if not exists public.activations (
  id uuid primary key default gen_random_uuid(),
  license_id uuid not null references public.licenses(id) on delete cascade,
  machine_fingerprint text not null,
  activated_at timestamptz not null default now(),
  last_seen timestamptz not null default now(),
  unique (license_id, machine_fingerprint)
);

alter table public.activations add column if not exists license_id uuid;
alter table public.activations add column if not exists machine_fingerprint text;
alter table public.activations add column if not exists activated_at timestamptz;
alter table public.activations add column if not exists last_seen timestamptz;
update public.activations set activated_at = now() where activated_at is null;
update public.activations set last_seen = now() where last_seen is null;
alter table public.activations alter column activated_at set not null;
alter table public.activations alter column last_seen set not null;
alter table public.activations alter column activated_at set default now();
alter table public.activations alter column last_seen set default now();

create index if not exists idx_activations_license_id on public.activations(license_id);

create table if not exists public.license_sessions (
  id uuid primary key default gen_random_uuid(),
  license_id uuid not null references public.licenses(id) on delete cascade,
  machine_fingerprint text not null,
  session_token text not null unique,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  last_seen timestamptz not null default now()
);

alter table public.license_sessions add column if not exists license_id uuid;
alter table public.license_sessions add column if not exists machine_fingerprint text;
alter table public.license_sessions add column if not exists session_token text;
alter table public.license_sessions add column if not exists expires_at timestamptz;
alter table public.license_sessions add column if not exists created_at timestamptz;
alter table public.license_sessions add column if not exists last_seen timestamptz;
update public.license_sessions set created_at = now() where created_at is null;
update public.license_sessions set last_seen = now() where last_seen is null;
alter table public.license_sessions alter column created_at set not null;
alter table public.license_sessions alter column last_seen set not null;
alter table public.license_sessions alter column created_at set default now();
alter table public.license_sessions alter column last_seen set default now();

create index if not exists idx_license_sessions_license_id on public.license_sessions(license_id);
create index if not exists idx_license_sessions_token on public.license_sessions(session_token);

alter table public.licenses enable row level security;
alter table public.activations enable row level security;
alter table public.license_sessions enable row level security;

-- No public policies: access only through Edge Functions via service_role.
