# Release checklist after the code split

## Vercel entry point

For a repository-root FastAPI deployment, `pyproject.toml` explicitly selects
`backend.main:app`. Use the repository root as Root Directory and FastAPI as the framework;
do not point this API project at `frontend/`. Leave custom build/output overrides unset.
The `.vercelignore` allowlist excludes local credentials, SQLite data, tests and caches.
Configure backend secrets in Vercel environment settings; local `.env` is not uploaded.
This resolves entry-point discovery only. Database setup below and separate job execution
remain required; a successful API build does not start `backend.worker`.

The application now uses Supabase Postgres as its sole production database. Earlier notes
about an active SQLite disk and two-way Supabase mirror are superseded by this architecture.

1. Correct `SUPABASE_DB_URL`: the existing live check returns password authentication failed.
2. Apply `supabase/migrations/202610270001_app_database.sql`, verify the private schema and RLS,
   import the existing local data into the empty private schema, then compare counts and records.
   Local data/backups have not been deleted; no live import has occurred.
3. Verify login, signup confirmation, recovery and OAuth using Supabase on the final frontend URL.
   Frontend/public key configuration and exact CORS/redirect URLs must match that URL.
4. Deploy the static frontend to Vercel in the next phase. Select hosting for the Python API and
   one persistent worker; configure a same-origin API proxy and use the same stable server
   configuration across API/worker. There is no production deployment in this change.
5. Configure production email delivery through Supabase in the following phase. Additional lead
   notifications default off; no separate notification service is required for the initial app.
6. Configure/test payments after email, including signed webhooks, renewal, failed payment,
   cancellation and manual refunds. Existing checkout remains disabled until its launch gates.
7. Review operator details/policies, YouTube use-case approval and measured Gemini cost/quality.
   Approval flags remain false; working API access is not approval or verified commercial margin.
8. Configure Supabase backups and test restore, queue restart and deletion. Inventory legacy
   public mirror data, local copies and external email/provider logs before discarding anything.
   The new private schema does not automatically remove old external copies.

Validation uses isolated SQLite regressions, real disposable Postgres integration tests,
frontend auth contract checks and separate frontend/API HTTP smoke tests. Local interactive
browser verification was unavailable because browser use is disabled in Work settings. Live
Supabase authentication/migration and provider email/payment tests remain unverified.
