# Verification — 27 October 2026

- Full Python suite: **137 passed**. Includes seven integration tests on a real, disposable
  PostgreSQL instance: private schema/RLS, identity provisioning, direct saves/scoring,
  transaction limits, verified sessions, queued jobs/outcomes, and read-only legacy import.
- Frontend session/API checks: **4 passed** with Node's test runner.
- Separated HTML/CSS/JS build and syntax checks passed.
- Independent frontend and backend HTTP smoke checks passed; API CORS returned the exact
  frontend origin. Public auth configuration contained no private credentials.
- Compared actual private credential values against all frontend artifacts: zero matches.
- Rehearsed import of the existing local data into disposable Postgres: 2 users, 3 workspaces,
  1,812 leads, 10 jobs and 4 runs. Counts matched, and the original data.db hash was unchanged.
- Read-only checks of the supplied live Supabase public Auth key and server API key returned
  HTTP 200. The SQL database connection still fails password authentication.
- The production API imports without SQLite access; retired mirror/key-editing routes are absent.
- Old root monoliths, duplicated static frontend, obsolete SQL mirror file and Render manifest
  were removed. Original .env, data.db and backups were preserved.

These are local/disposable-database checks, not a live database migration or production launch.
Interactive browser testing was unavailable because local browser use is disabled in Work
settings. No signup emails, payment transactions, YouTube searches or Gemini generations were
performed during this split. Vercel deployment, email delivery and payment activation remain
separate later phases.

Known non-failing test warnings: FastAPI on_event deprecation and Starlette/httpx test-client
compatibility deprecation. The API lifecycle can move to lifespan handlers in a later cleanup.
