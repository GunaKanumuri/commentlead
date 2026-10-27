# Private launch tracking

In Supabase, open **SQL Editor**, paste this query and click **Run**.
Only the database operator can read this data; there is no public analytics endpoint.

```sql
SELECT day,
  COUNT(*) FILTER (WHERE page_views > 0) AS daily_visitors,
  SUM(page_views) AS page_views,
  SUM(preview_attempts) AS preview_attempts,
  COUNT(*) FILTER (WHERE previews_with_results > 0) AS visitors_with_results,
  SUM(previews_with_results) AS previews_with_results,
  SUM(empty_previews) AS previews_without_results,
  SUM(preview_errors) AS preview_errors,
  SUM(comments_returned) AS comments_returned
FROM app_private.site_usage_daily
GROUP BY day ORDER BY day DESC;
```

To check waitlist demand:

```sql
SELECT interest, COUNT(*) AS signups
FROM app_private.waitlist
GROUP BY interest ORDER BY signups DESC;
```

Days use UTC. Visitors are approximate daily browser counts, not identified people:
cookie clearing, separate devices and automated requests affect them. Summing daily
visitors across days gives visitor-days, not unique people for the whole period.
Page views count successful homepage HTTP requests (including bots), not visual page rendering.
Preview outcomes are recorded by the server, not accepted from browser-supplied statistics.
A preview with results returned at least one comment; these are not verified buyers.
Errors include rejected, rate-limited and provider-failed requests. Returning comments
does not prove they rendered or were read. No searches, comments, email addresses,
raw IP addresses or external analytics services are used for these counters.

Usage is best-effort: storage failures log a generic warning and do not break the app.
Counters expire after 90 days, cleaned on the next tracked request, even without a worker.
Tracking starts when this code is deployed; historical traffic cannot be reconstructed.
No new API keys or admin account are needed. Vercel still needs its database connection.
