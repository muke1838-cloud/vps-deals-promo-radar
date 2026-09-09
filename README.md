# VPS Deals Promo Radar

Public snapshots of VPS pricing and promotions from official provider pages. Static site. No runtime LLM. No API keys.

**Live site:** https://vps-deals-promo-radar-9p1.pages.dev  
**This repo:** https://github.com/muke1838-cloud/vps-deals-promo-radar

## Defaults filled on first build

The operator brief left inputs empty. These defaults are marked here so they are not silent:

| Input | Value used |
| --- | --- |
| NICHE | VPS hosting |
| BRAND | vps-deals |
| LOCALE | en-US |
| LIST | DigitalOcean, Hetzner, Contabo, OVHcloud, Hostinger — official pricing/product pages listed in `.ilang/site.ilang` |

Vultr and Linode official pages returned HTTP 403 to this project's declared user-agent on 2026-09-09. They are not in v1. Adding them later is a one-line change in `.ilang/site.ilang`.

Affiliate slots are empty. Outbound buttons use the provider URL. Commissions are not listed.

## How it works

1. `scraper.py` reads `.ilang/site.ilang`, respects robots.txt, fetches those URLs, and writes `data/offers.json`.
2. `build.py` reads the same config plus `offers.json` and writes `site/`.
3. GitHub Actions runs both every 6 hours and commits if the snapshot changed.
4. Cloudflare Pages publishes `site/` (build command `python3 build.py`, output `site/`).

If a public page has no machine-readable price, the `price` field is omitted. Expired `valid_until` values are marked expired and are not shown as in-stock.

```bash
python3 scraper.py
python3 build.py
python3 -m unittest tests/test_pipeline.py
```

## Change the crawl list

Edit `.ilang/site.ilang` providers, then rerun scraper and build. The HTML follows that file. Do not add a second list in Python.

Site rules are described with the I-Lang protocol in `.ilang/site.ilang`. Protocol notes: https://ilang.ai
