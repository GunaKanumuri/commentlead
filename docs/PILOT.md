# Ten-person customer-discovery pilot

Status: awaiting participant details. No invitations, accounts, results or purchases have been fabricated.
Target: five software founders (F01–F05) and five homemade sellers (H01–H05).

## Participant roster

Use aliases here. Each participant registers their own account and keeps their own password.

| ID | Cohort | Alias / business | Website or product summary | Onboarding status |
| --- | --- | --- | --- | --- |
| F01 | Software founder | Pending | Pending | Pending |
| F02 | Software founder | Pending | Pending | Pending |
| F03 | Software founder | Pending | Pending | Pending |
| F04 | Software founder | Pending | Pending | Pending |
| F05 | Software founder | Pending | Pending | Pending |
| H01 | Homemade seller | Pending | Pending | Pending |
| H02 | Homemade seller | Pending | Pending | Pending |
| H03 | Homemade seller | Pending | Pending | Pending |
| H04 | Homemade seller | Pending | Pending | Pending |
| H05 | Homemade seller | Pending | Pending | Pending |

## Onboarding interview

For each participant confirm: product and three actual features; ideal buyer; problem solved;
service countries/cities or delivery boundary; supported languages; actual price and currency;
known alternatives; excluded customers; and unsupported features or fulfilment limits.
The participant reviews the generated description before searching. Do not infer these answers
from their name or language. An alias and product description are enough for initial planning;
passwords and API keys must never be collected in this document.

## Comparable first session

Give each participant the same initial allowance: up to two searches, and manual review of
up to ten accessible, genuinely sourced comments. Record the actual number surfaced when
fewer than ten are available. Record whether the software or a human assisted each review.
Do not automatically change their paid plan or bypass existing lead limits.

For every reviewed comment, verify the source and date when available, actual customer need,
matching product capability, any delivery/budget conflict, and unknowns. Mark useful or not
useful independently of the AI score. A request for free help or a seller promotion is not
sufficient evidence of a relevant purchase need.

Use these rejection categories in the lead outcome reason: no purchase need; wrong product;
wrong service area; incompatible budget; seller promotion; student/tutorial request; stale
request; duplicate; or insufficient evidence. Keep the exact supporting comment available.

## Conversations and outcomes

Participants decide whether a manual reply is appropriate and send it themselves. No automated
posting or contact discovery is part of this pilot. Over 7–14 days record contacted, responded,
qualified, purchased, or irrelevant in the app. A qualified conversation requires a confirmed
relevant need and willingness to discuss the offer. Only record a purchase when reported by
the participant; copying a reply is not a response or a sale. Record revenue and currency separately.

Ask “After using these results, would you pay to use this again?” in Pilot feedback, then capture
why, what they would pay, and the improvements that would change their answer. Willingness
statements and actual payments must remain separate. Participation is counted in the admin
cohort view after feedback is submitted.

## Comparison scorecard

For founders and homemade sellers separately record:

- distinct participants and number who completed onboarding;
- comments surfaced and comments manually reviewed;
- useful comments / reviewed comments;
- participants who found at least three useful prospects;
- contacts, replies, qualified conversations and reported purchases;
- replies / contacts, with both counts shown and no percentage when denominator is zero;
- willingness to pay: yes / no / undecided and associated reasons;
- estimated API cost per useful lead, with unknown pricing or missing usage explicitly unknown;
- rejection categories, delivery uncertainty, language errors and stale requests.

The app funnel reports current outcome stages. For cumulative movement use the local outcome
event history; do not treat the current contacted-stage count as everyone ever contacted.
Do not combine revenue across currencies. With five people per cohort the results are
directional; do not extrapolate a market conversion rate.

## Launch gates

- Local database migration: applied; existing lead text, status and feedback preserved.
- Cloud schema: must be applied and verified against the actual Supabase project.
- Service-role key: configure server-side in `.env`; never place it in this document or browser.
- Database connectivity: needs a working `SUPABASE_DB_URL` before a psql rollout.
- Hosting: persistent `DB_PATH`, stable private `JWT_SECRET`, one application process.
- Email delivery: verify separately before promising email alerts.
- Participant recruitment: user has indicated participants are available; roster details pending.

Do not schedule a pilot start date until participants can sign in and these live prerequisites pass.
