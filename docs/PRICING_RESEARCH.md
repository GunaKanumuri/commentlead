# Launch pricing decision — 27 October 2026

## Recommendation

Sell **matched opportunities**, with an explicit separate comment-analysis and discovery-run cap.
A matched opportunity is a source-backed comment assessed as relevant, not a verified buyer,
contact record, guaranteed response or guaranteed sale. Allowances are maximums: suitable
comments may not exist. Two Boost products share one account allowance.

| Tier | Price | New matches | Comments analysed | Discovery runs | Products |
|---|---:|---:|---:|---:|---:|
| Free Trial | ₹0, one seven-day trial | up to 30 total | 150 total | 2 total | 1 |
| Starter | ₹499 / billing month | up to 200 | 2,000 | 5 | 1 |
| Boost | ₹999 / billing month | up to 1,000 | 8,000 | 10 | 2 |

Reassessment consumes analysis allowance. Paid renewals require a verified paid provider
period, rather than resetting a counter on the first of each month. Unused allowances do not
roll over. Previously unlocked results do not consume another match credit; availability is
subject to source refresh/deletion. Weekly Boost automation consumes the same run allowance.
Avoid 2,000 matches at ₹999 until actual yield, source availability, quality and cost are measured.
Do not launch annual billing until retention and repeat value are established.

## What the research establishes

These are published offers, not evidence of paid conversion, retention or willingness to pay
among Indian founders or homemade sellers. No customer interviews or paid tests were conducted.

| Alternative | Observed published offer | Comparability |
|---|---|---|
| [Buska](https://www.buska.io/) | Starter $49/month; Growth $99/month; seven-day trial | Broad social listening and buying signals across multiple sources; stronger breadth than this YouTube-first product |
| [KeyComment](https://keycomment.com/) | Starter €29/month and Pro €69/month, explicitly billed annually on the page | Self-hosted/BYO LLM keys; displayed price excludes the buyer's model usage |
| [F5Bot](https://f5bot.com/) | Free keyword alerts for Reddit, Hacker News and Lobsters | A free substitute for manual discovery; finding mentions alone is insufficient differentiation |

**Inference:** ₹499 and ₹999 are sensible low-price experiments for a narrower product. Their
being cheaper than these published international plans does not prove demand. Start with
software founders who can evaluate global customer conversations. For local homemade sellers,
test usefulness separately: unverified delivery location can make even cheap matches worthless.

## How to test willingness to pay

1. Manually review 20 real source comments per participant, with their permission. Record useful
   matches, source age, location/budget unknowns and time saved. Do not promise paid volume yet.
2. Recruit actual prospects before drawing commercial conclusions. The founder's manual tests
   establish quality; they do not establish willingness to pay.
3. Offer Starter at ₹499 after showing useful results. If possible, use the same pilot benefits
   for comparable participants; record the offer and reason for refusal. Count completed
   payment and second-month renewal, not “I would pay.” Enable payments only after launch gates.
4. If ₹499 fails despite useful results, test ₹299 as a clearly disclosed, time-limited
   introductory offer. Do not silently promise lifetime ₹299 or add a fourth permanent tier.
5. Offer ₹999 Boost when a second product or higher usable volume is an observed need. Do not
   infer an upsell from a high raw-comment count.

For an initial directional test, aim for ten eligible Starter offers and record the complete
funnel: offered → accepted → paid → contacted → responded → qualified → purchased → renewed.
Ten people is too small for a reliable market-wide conversion estimate. Suggested internal
decision bars, **not industry benchmarks**: at least three completed payments, independently
reviewed usefulness on at least half the presented matches, some real customer responses,
and measured positive contribution margin. Review rejection reasons before changing price.

## Cost: why the allowances remain gated

[Google's current Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) lists
Gemini 3.5 Flash at $1.50/M input and $9/M output tokens, and Gemini 3.5 Flash-Lite at
$0.30/M input and $2.50/M output tokens. Output includes thinking where applicable.
Prices depend on model/service and must be rechecked before launch.

Illustration only: 150 input and 150 output tokens **per analysed comment**, excluding
setup/query generation, repeated product context, reports, retries, taxes, hosting, payment
fees, support and acquisition. These token assumptions have not been measured on this app.

| Full monthly analysis use | Flash model cost | Flash-Lite model cost |
|---|---:|---:|
| Starter: 2,000 comments | $3.15 | $0.84 |
| Boost: 8,000 comments | $12.60 | $3.36 |

At an illustrative ₹90/$ (not a live exchange quote), Boost's Flash analysis alone would be
₹1,134, exceeding ₹999 revenue. A cheaper model may help, but it must pass the same match-quality
review. The actual model configuration was not switched automatically. Configure real token
rates in `GEMINI_PRICING_JSON`, collect input/output/thinking usage from representative runs,
and include all costs before setting `PRICING_UNIT_ECONOMICS_VERIFIED=true`.

## First 100 customers and YouTube

[Google's quota calculator](https://developers.google.com/youtube/data/determine_quota_cost)
documents 100 `search.list` calls/day in a separate bucket and 10,000 daily units for other
endpoints. Comment listing costs one unit and can return multiple comments. This is **not
10,000 qualified leads/day**. Retries and pagination consume capacity.

The configured search budget is 90/day: paid 75, trial 10, public preview 5. At two searches
per paid discovery run, 100 Boost accounts fully using ten runs/month require 2,000 search
calls/month, about 67/day on average. That average leaves little headroom for retries and
uneven demand; the queue may defer work and provider limits remain authoritative. It does
not guarantee 100 accounts can receive their match maximums. A mixed 70 Starter/30 Boost
cohort uses about 43 search calls/day at full run usage, before retries and previews.

Adding YouTube accounts or API keys does not create legitimate extra capacity for this same
application. Google's [developer policy guide](https://developers.google.com/youtube/terms/developer-policies-guide)
prohibits quota sharding; use the official [quota extension/audit process](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits).
The [data policies](https://developers.google.com/youtube/terms/developer-policies) and
[derived metrics policy](https://developers.google.com/youtube/terms/derived-metrics-policy)
need review for this comment-prospecting/AI-classification use case. Existing API access is
not evidence of approval. `YOUTUBE_USE_CASE_APPROVED` remains false.

## Trial abuse and commercial honesty

Implemented controls: verified email in production, Gmail alias normalization, signed browser
trial identity, keyed identity hashes, IP signup/preview/trial throttles, one trial period,
separate preview capacity and server-side allowances. Different emails, browsers and networks
can still bypass some controls. Avoid invasive fingerprinting or a claim of perfect prevention.
If abuse is observed, evaluate additional verification using actual loss and conversion data.

No real charges, refunds, customer outreach or deployment were performed during this work.
