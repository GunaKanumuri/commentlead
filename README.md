# Comment → Money

A small customer-discovery app: add a product, find source-backed matches, and track conversations.

The current public launch offers free product-specific matching and a simple email waitlist.
Visitors enter working features, target customers, product stage and optional constraints.
A preview checks up to three videos (35 comments each), assesses up to 60 recent candidates
with Gemini, and returns up to five potential matches with exact source/feature quotes and
unknowns. No unrelated fallback comments are displayed. Empty results describe this limited
search, not overall market demand. Public preview requires `GEMINI_API_KEY` alongside YouTube
and database settings; `PREVIEW_DAILY_AI_REQUEST_BUDGET` caps public AI requests including retries.
There is no public signup, password, account dashboard or checkout. Upcoming features open
the waitlist dialog. Set `PUBLIC_LAUNCH_MODE=waitlist` (the default) to keep private routes closed.
Waitlist entries are stored in the private Supabase `waitlist` table with consent and referral
source; duplicate emails do not create additional entries. No email is sent on submission.
Private daily visit and preview counters are available in Supabase; see
[the analytics queries](docs/ANALYTICS.md). No public admin dashboard is needed.

## Project layout

```text
frontend/               Public preview, waitlist dialog and API client
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
6. A worker is only needed when restoring the full product; the public preview runs directly.
7. Start the frontend: `python -m scripts.dev_frontend` and open `http://localhost:3000`.

Use `FRONTEND_URL=http://localhost:3000` and allow that exact origin in `ALLOWED_ORIGINS`.
The frontend does not receive database, Supabase secret, YouTube or Gemini credentials.

Supabase Auth integration remains in the backend for the later full-product launch.
The current public frontend does not load an authentication SDK or create accounts.
All product data goes through the Python API into Supabase Postgres. There is no application
SQLite fallback or two-way data mirror. SQLite exists only in explicitly isolated legacy tests.

## Current setup status

Supabase database authentication now works, and the private application schema has been
applied and verified. The existing local records have not been imported; their database and
backups remain preserved. Configure the same server credentials in Vercel's Environment
Variables: local `.env` is intentionally excluded from deployment uploads.

See [setup](docs/SETUP.md), [architecture](docs/ARCHITECTURE.md), and [release checklist](docs/PREDEPLOY.md).

## Next phases

1. Configure server environment variables in Vercel and verify the public preview and waitlist.
2. Review the first real comments and collect waitlist demand.
3. Restore accounts, email delivery and paid features after validating demand.

These steps are not deployed or activated by the code split. Paid checkout remains gated.
