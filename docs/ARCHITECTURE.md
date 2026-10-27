# Architecture

```text
Browser frontend ── Supabase Auth API (signup/login/verification/recovery/refresh)
       │
       └── Bearer Supabase session ── Python HTTP API ── Supabase Postgres
                                         │                    │
                                    YouTube/Gemini       Persistent job queue
                                                              │
                                                     One Python worker
```

No database writes occur in the browser. The public configuration endpoint returns only the
Supabase project URL, public key and storage mode. Secret keys and database credentials never
enter the frontend build. Supabase Auth is the sole production password/session authority.
Legacy custom JWTs are not accepted in the Supabase data path.

`backend/runtime.py` is the composition boundary that wires focused service files. Existing
services share that explicit boundary so ownership, quota, evidence, billing and lifecycle
behavior stays consistent during the split. `backend/commercial.py` only groups the entitlement,
queue, billing and lifecycle services. Neither file contains the previous monolithic handlers.
`backend/main.py` exposes the FastAPI app; `backend/worker.py` is a separate process.

`backend/database.py` provides parameterized SQL, typed rows and transaction handling. A small
DB-API adapter supports the existing qmark queries and explicit short mutation locks while
using Postgres. Its advisory locks are transaction-scoped for pooler compatibility. Production
never creates SQLite files, runs SQLite schema migrations or writes a secondary data mirror.
The SQLite fixture is limited to explicitly isolated tests and is rejected in production.

All 20 application tables plus a schema-version table live in `app_private`. RLS is enabled,
browser privileges are revoked, and the schema is not exposed through PostgREST. API ownership
checks apply before reading/updating workspaces or leads. Trial grants, usage, provider costs,
billing events, outcomes and lifecycle state live in the same database as product data.

The complete schema is applied explicitly by the migration tool or Supabase SQL Editor, never
by an HTTP request. The former public-schema mirror is untouched for safe migration; it is not
used as the application data source. Existing public copies require retention review and an
explicit cleanup plan after cutover. No destructive cloud-table changes were made.

Separate API/frontend origins are supported for development with exact CORS origins. For the
later Vercel launch, prefer a same-origin /api proxy so essential cookies do not depend on
third-party-cookie support. The backend worker still needs a suitable execution environment;
splitting files does not turn persistent background jobs into Vercel request handlers.
