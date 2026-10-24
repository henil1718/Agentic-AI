# Multi-Agent Pipeline

A local React/Vite dashboard streams mock Architect, Coder, and Deployer agent
outputs through Supabase Realtime. FastAPI runs the agents sequentially and
stores each output in `public.agent_logs`.

## 1. Create the Supabase table

In the Supabase SQL Editor, run [`backend/schema.sql`](./backend/schema.sql):

```sql
create table if not exists public.agent_logs (
  id uuid primary key default gen_random_uuid(),
  run_id text not null,
  agent_role text not null,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

alter table public.agent_logs disable row level security;

alter publication supabase_realtime add table public.agent_logs;
```

Disabling RLS makes this table accessible without row-level protections. This
is intended only for a local/demo setup; use appropriate RLS policies for a
production deployment.

## 2. Configure environment variables

If you do not already have these files, copy `backend/.env.example` to
`backend/.env` and `frontend/.env.example` to `frontend/.env` (for example,
`cp -n .env.example .env` from each directory). Set the project URL and a
server-side Supabase key in the backend file. Keep the server-side key private;
do not use it in the frontend.

Set the same project URL and the Supabase anon/publishable key in the frontend
file. Vite exposes `VITE_` variables to the browser, so never put a service-role
key there.

## 3. Install and start the backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

The API accepts a JSON request at `POST http://127.0.0.1:8000/api/trigger`:

```json
{
  "prompt": "Build a rate-limited auth microservice"
}
```

It immediately returns a `run_id`; the three mock agents then each wait one
second and insert their result into `agent_logs`.

## 4. Install and start the frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite. `npm run build` runs the TypeScript
type-check and production build.
