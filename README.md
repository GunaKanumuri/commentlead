# Comment → Money

A small customer-discovery app: add a product, find source-backed matches, and track conversations.

## Project layout

```text
frontend/               HTML, CSS, JavaScript, Supabase login, API client
backend/                Python API and focused services
  main.py               HTTP entry point
  auth.py               Verify Supabase sessions and provision profiles
  database.py           Supabase Postgres connection and transactions
  providers.py          YouTube and Gemini integration
  matching.py           Comment selection, scoring and evidence
  jobs.py, worker.py    Persisted discovery jobs and the worker
  lifecycle.py          Retention, privacy, deletion
supabase/migrations/    Complete private application database schema
scripts/                Database migration and local frontend tools
tests/                  Isolated regressions and real Postgres tests
docs/                   Setup, architecture, pilot and launch notes
```

## Start here

1. Install dependencies: `pip install -r requirements.lock`.
2. Keep server credentials in the existing `.env`. See `.env.example`.
3. Verify the database: `python -m scripts.manage_database --check`.
4. For a new database, apply the schema: `python -m scripts.manage_database --apply`.
5. Start the API: `uvicorn backend.main:app --reload --port 8000`.
6. Start one worker: `python -m backend.worker`.
7. Start the frontend: `python -m scripts.dev_frontend` and open `http://localhost:3000`.

Use `FRONTEND_URL=http://localhost:3000` and allow that exact origin in `ALLOWED_ORIGINS`.
The frontend does not receive database, Supabase secret, YouTube or Gemini credentials.

Supabase Auth manages signup, login, email confirmation, password recovery and session refresh.
All product data goes through the Python API into Supabase Postgres. There is no application
SQLite fallback or two-way data mirror. SQLite exists only in explicitly isolated legacy tests.

## Current setup status

Supabase database authentication now works, and the private application schema has been
applied and verified. The existing local records have not been imported; their database and
backups remain preserved. Configure the same server credentials in Vercel's Environment
Variables: local `.env` is intentionally excluded from deployment uploads.

See [setup](docs/SETUP.md), [architecture](docs/ARCHITECTURE.md), and [release checklist](docs/PREDEPLOY.md).

## Next phases

1. Complete and verify the live Supabase schema/data migration.
2. Vercel frontend deployment and backend/worker hosting.
3. Supabase email delivery configuration.
4. Payments and a controlled pilot.

These steps are not deployed or activated by the code split. Paid checkout remains gated.
