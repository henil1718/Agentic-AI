create table if not exists public.agent_logs (
  id uuid primary key default gen_random_uuid(),
  run_id text not null,
  agent_role text not null,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

alter table public.agent_logs disable row level security;

alter publication supabase_realtime add table public.agent_logs;
