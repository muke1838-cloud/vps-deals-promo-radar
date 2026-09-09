# Test plan: VPS Deals Promo Radar v1 pipeline

Feature: public, no-runtime-LLM coupon niche site. Config is `.ilang/site.ilang`. Scraper and builder are deterministic Python. Prices come only from public provider pages.

Locale under test: en-US. Brand under test: vps-deals.

## Coverage map

| Requirement | Cases |
| --- | --- |
| site.ilang is the only provider list | T01, T02, T10 |
| Missing price is omitted, never estimated | T03, T04, T11 |
| Expired valid_until is not shown as active | T05, T06 |
| JSON-LD / canonical / sitemap honesty | T07, T08, T09 |
| Fetch failures do not invent offers | T11 |
| Affiliate empty => bare provider URL | T12 |
| Workflow exists and is scheduled | T13 |
| Public pages build from committed data | T14, T15 |

## Cases

### T01 — Parse providers from site.ilang
- Priority: P0
- Scene: normal
- Preconditions: fixture `tests/fixtures/site.ilang` with three providers
- Steps: load config via `ilang_site.load_site_config`
- Data: names Alpha, Beta, Gamma
- Expected: exactly those three, in file order; affiliate empty becomes null
- Evidence: unittest `test_parse_providers`

### T02 — Removing a provider changes the site
- Priority: P0
- Scene: config change
- Preconditions: offers.json contains Alpha and Beta; site.ilang only lists Beta
- Steps: run `build.py` against that config
- Expected: index and compare have Beta, not Alpha; no Alpha provider page
- Evidence: unittest `test_build_follows_ilang_providers`

### T03 — JSON-LD Offer without price does not get a price field
- Priority: P0
- Scene: partial structured data
- Preconditions: HTML fixture with Offer missing `price`
- Steps: run extractor
- Expected: offer exists with title/url; `price` and `currency` keys absent; no schema price on the deal page
- Evidence: unittest `test_missing_price_omitted`

### T04 — Extractor never fills price from guesses
- Priority: P0
- Scene: HTML contains unrelated dollar amounts in CSS or FAQ
- Preconditions: fixture with `$200` in a stylesheet and no JSON-LD Offer
- Steps: run extractor
- Expected: no priced offer; optional page-entry offer has no price
- Evidence: unittest `test_does_not_guess_dollar_amounts`

### T05 — Past valid_until is expired
- Priority: P0
- Scene: stale coupon
- Preconditions: offer valid_until=2020-01-01
- Steps: build
- Expected: status expired; not in homepage active list; deal page visible text includes Expired; Offer JSON-LD not marked InStock
- Evidence: unittest `test_expired_not_active`

### T06 — Missing valid_until is allowed
- Priority: P1
- Scene: ongoing public pricing
- Preconditions: offer has price, no valid_until
- Steps: build
- Expected: active if fetch succeeded; JSON-LD omits priceValidUntil
- Evidence: unittest `test_missing_valid_until_ok`

### T07 — Deal page JSON-LD uses Offer only when price exists
- Priority: P0
- Scene: schema honesty
- Preconditions: one priced Contabo-like offer, one unpriced DigitalOcean-like entry
- Steps: build, parse script[type=application/ld+json]
- Expected: priced page has Offer or AggregateOffer with priceCurrency; unpriced page has no price / priceCurrency
- Evidence: unittest `test_jsonld_price_gate`

### T08 — Canonical points at itself
- Priority: P0
- Scene: index, provider, deal, compare
- Expected: `<link rel="canonical">` equals the page URL on the configured domain
- Evidence: unittest `test_canonical_self`

### T09 — sitemap lastmod is fetch time
- Priority: P1
- Scene: sitemap.xml
- Expected: lastmod from offer fetched_at or generated_at, not a hardcoded date; no expired-as-fresh requirement beyond real timestamps
- Evidence: unittest `test_sitemap_lastmod`

### T10 — Builder does not keep a hardcoded provider list
- Priority: P0
- Scene: grep/source check
- Expected: `build.py` and `scraper.py` have no DigitalOcean/Contabo name constants used as the crawl list; list comes from parsed ilang
- Evidence: unittest `test_no_hardcoded_provider_list` plus code review

### T11 — HTTP 403 does not create a fake priced deal
- Priority: P0
- Scene: fetch failure
- Preconditions: scraper fetch returns 403
- Expected: provider fetch recorded as error; offers array has no invented price for that provider
- Evidence: unittest `test_fetch_error_no_fake_offer` (mocked)

### T12 — Empty affiliate uses offer URL
- Priority: P1
- Scene: monetize v1
- Expected: outbound CTA href is offer_url; rel does not include sponsored unless affiliate set
- Evidence: unittest `test_bare_link_without_affiliate`

### T13 — Actions cron every 6 hours
- Priority: P0
- Scene: workflow file
- Expected: `.github/workflows/update.yml` has `cron: "0 */6 * * *"` and runs scraper then build
- Evidence: unittest `test_workflow_cron` and file in repo

### T14 — Local build produces site/
- Priority: P0
- Scene: developer and Pages
- Steps: `python3 scraper.py` (network) then `python3 build.py`
- Expected: `site/index.html`, provider pages, compare, robots.txt, sitemap.xml exist
- Evidence: command output and file list recorded in this plan after the run

### T15 — Live pages.dev URLs return 200
- Priority: P0
- Scene: production acceptance
- Steps: GET homepage, `/compare/`, `/robots.txt`, `/sitemap.xml`
- Expected: HTTP 200; HTML contains brand; sitemap lists the same host
- Evidence: curl -sI recorded here after deploy. Do not mark complete without URLs.

## Boundaries not covered as pass

- Buying a custom domain
- Affiliate enrollment / commissions (must stay empty until a real program URL is provided)
- Vultr/Linode HTML, which returned HTTP 403 to this project's user-agent in the 2026-09-09 probe and are therefore not in the v1 list

## Run log

| ID | Result | Evidence | When |
| --- | --- | --- | --- |
| T01–T13 | pass | `python3 -m unittest tests/test_pipeline.py` — 15 tests OK | 2026-09-09 |
| T14 | pass | `python3 scraper.py` wrote 5 providers / 4 offers / 3 priced (Contabo JSON-LD only). `python3 build.py` wrote 12 page records under `site/` | 2026-09-09 |
| T15 | pending | public URL | |
