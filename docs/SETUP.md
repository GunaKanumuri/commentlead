# Setup

## Server configuration

Keep `.env` at the project root. Do not copy it into `frontend/` or a static hosting build.
The backend reads the existing Supabase, YouTube and Gemini keys.

Required: `SUPABASE_URL`, `SUPABASE_ANON_KEY` (or `SUPABASE_PUBLISHABLE_KEY`),
`SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_SECRET_KEY`), and `SUPABASE_DB_URL`.
The SQL URL must use the actual database password, URL-encoded if it contains special characters.
Prefer the Supabase pooler connection URL shown in Connect. Prepared statements are disabled
for transaction-pooler compatibility. TLS is required by default.

Keep `JWT_SECRET` stable: it signs essential trial identity hashes/cookies, not customer login
sessions. Customer sessions are verified through Supabase Auth. AI keys remain backend-only.

## Database

```text
python -m scripts.manage_database --check
python -m scripts.manage_database --apply
python -m scripts.manage_database --check
```

The migration creates a private `app_private` schema and all application tables, ledgers and
indexes. It is repeatable and does not drop existing public mirror tables or user data.
Browser roles have no table/schema access. The backend database role accesses this schema;
HTTP endpoints enforce account ownership. Do not expose `app_private` through the Data API.

## Preserve and import existing data

The old `data.db` and `.local-backups/` are preserved. Stop the old application before a final
cutover, take a SQLite backup, and import into an empty private application database:

```text
python -m scripts.manage_database --import-sqlite data.db
```

Import is transactional, preserves IDs and data, advances identity sequences, and reads the
source database in read-only mode. It refuses an occupied destination instead of overwriting
existing Supabase users. Imported password hashes are cleared: users authenticate through
Supabase, whose verified email/identity maps them to their existing product records.
Never delete local data until row counts and representative leads/outcomes are verified live.
The current live import is blocked by SQL authentication and has not been performed.

## Local processes

```text
uvicorn backend.main:app --reload --port 8000
python -m backend.worker
python -m scripts.dev_frontend
```

Use one worker for this first deployment. It recovers saved running requests when restarted;
provider work may repeat, but result uniqueness and usage budgets remain enforced. API imports
perform no database migrations or scheduler work. API replicas do not start background threads.
The dedicated worker owns scheduling, lifecycle maintenance and queued job execution.

Set Supabase Auth Site URL and allowed redirects to the frontend URL. Default local frontend
is `http://localhost:3000`; API is `http://localhost:8000`. OAuth requires its provider to be
configured in Supabase. Email delivery remains a later setup phase. No emails are sent by setup.

For one-origin local inspection, the API also serves the frontend assets at its root URL.
For a static build run `python frontend/build.py`; `PUBLIC_API_BASE_URL` is the only build input.
The output is `frontend/dist/`. It does not copy `.env` or any private credentials.

## Checks

```text
python -m pytest -q
node --test tests/frontend.test.cjs
```

Legacy regressions use an explicitly enabled disposable SQLite fixture. Real Postgres checks
require `TEST_SUPABASE_DB_URL` pointing at the dedicated loopback database on port 55438;
they refuse non-loopback destinations. These are not live Supabase or production load tests.
