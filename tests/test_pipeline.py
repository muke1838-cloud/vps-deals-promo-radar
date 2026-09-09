# ::ILANG
# [TYPE:code][FILE:tests/test_pipeline.py]
# ::STATE{role:offline pipeline checks}
# ::BOUNDARY{never:assert invented live prices}

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ilang_site import load_site_config, parse_site_ilang  # noqa: E402
from scraper import parse_jsonld_offers, scrape_provider  # noqa: E402
import build as builder  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


PRICED_HTML = """<!doctype html><html><head>
<title>Cloud VPS 4</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Cloud VPS 4",
 "offers":{"@type":"AggregateOffer","lowPrice":6.6,"priceCurrency":"USD",
 "url":"https://vendor.example/vps/"}}
</script></head><body></body></html>
"""

NOPRICE_HTML = """<!doctype html><html><head>
<title>VPS</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"VPS",
 "url":"https://vendor.example/vps/"}
</script></head><body></body></html>
"""

DOLLAR_NOISE_HTML = """<!doctype html><html><head>
<title>Pricing</title>
<style>.x{content:"$200 credit"}</style>
</head><body><p>Talk to sales.</p></body></html>
"""


class ParseIlangTests(unittest.TestCase):
    def test_parse_providers(self) -> None:
        cfg = load_site_config(FIXTURES / "site.ilang")
        names = [p["name"] for p in cfg["providers"]]
        self.assertEqual(names, ["Alpha", "Beta", "Gamma"])
        self.assertIsNone(cfg["providers"][0]["affiliate_url"])
        self.assertEqual(cfg["providers"][1]["affiliate_url"], "https://aff.example/beta")
        self.assertEqual(cfg["site"]["brand"], "fixture-deals")


class ExtractorTests(unittest.TestCase):
    def test_missing_price_omitted(self) -> None:
        offers = parse_jsonld_offers(
            NOPRICE_HTML, "https://vendor.example/vps/", "Vendor", "2026-09-09T00:00:00+00:00"
        )
        self.assertTrue(offers)
        self.assertNotIn("price", offers[0])
        self.assertNotIn("currency", offers[0])

    def test_does_not_guess_dollar_amounts(self) -> None:
        offers = parse_jsonld_offers(
            DOLLAR_NOISE_HTML, "https://vendor.example/pricing", "Vendor", "2026-09-09T00:00:00+00:00"
        )
        priced = [o for o in offers if "price" in o]
        self.assertEqual(priced, [])

    def test_jsonld_price_kept(self) -> None:
        offers = parse_jsonld_offers(
            PRICED_HTML, "https://vendor.example/vps/", "Vendor", "2026-09-09T00:00:00+00:00"
        )
        priced = [o for o in offers if o.get("price") == "6.6"]
        self.assertTrue(priced)
        self.assertEqual(priced[0]["currency"], "USD")


class FetchErrorTests(unittest.TestCase):
    def test_fetch_error_no_fake_offer(self) -> None:
        provider = {
            "name": "Vultr",
            "slug": "vultr",
            "home_url": "https://www.vultr.com",
            "source_url": "https://www.vultr.com/pricing/",
            "affiliate_url": None,
        }
        fake = {
            "status": 403,
            "url": provider["source_url"],
            "content_type": "",
            "text": "",
            "truncated": False,
            "error": "Forbidden",
        }
        with patch("scraper.robots_allows", return_value=(True, "test")), patch(
            "scraper.http_get", return_value=fake
        ):
            result = scrape_provider(provider, "2026-09-09T00:00:00+00:00")
        self.assertEqual(result["record"]["status"], "fetch_error")
        self.assertEqual(result["offers"], [])


class BuildTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "generated_at": "2026-09-09T12:00:00+00:00",
            "offers": [
                {
                    "id": "alpha1",
                    "provider": "Alpha",
                    "provider_slug": "alpha",
                    "title": "Alpha Cloud",
                    "price": "9",
                    "currency": "USD",
                    "offer_url": "https://alpha.example/pricing",
                    "source_url": "https://alpha.example/pricing",
                    "fetched_at": "2026-09-09T12:00:00+00:00",
                    "status": "active",
                    "extract_method": "jsonld-offer",
                },
                {
                    "id": "beta1",
                    "provider": "Beta",
                    "provider_slug": "beta",
                    "title": "Beta Promo",
                    "offer_url": "https://beta.example/deals",
                    "source_url": "https://beta.example/deals",
                    "fetched_at": "2026-09-09T12:00:00+00:00",
                    "status": "active",
                    "extract_method": "jsonld-product",
                },
                {
                    "id": "old1",
                    "provider": "Beta",
                    "provider_slug": "beta",
                    "title": "Old coupon",
                    "price": "1",
                    "currency": "USD",
                    "offer_url": "https://beta.example/old",
                    "source_url": "https://beta.example/deals",
                    "fetched_at": "2020-01-01T00:00:00+00:00",
                    "valid_until": "2020-01-01",
                    "status": "active",
                    "extract_method": "jsonld-offer",
                },
            ],
            "providers": [],
        }

    def test_build_follows_ilang_providers(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_path = tmp_path / "offers.json"
            site_dir = tmp_path / "site"
            data_path.write_text(json.dumps(payload), encoding="utf-8")
            builder.build(
                config_path=FIXTURES / "site-beta-only.ilang",
                data_path=data_path,
                site_dir=site_dir,
            )
            index = (site_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn("Beta", index)
            self.assertNotIn("Alpha Cloud", index)
            self.assertTrue((site_dir / "providers" / "beta" / "index.html").exists())
            self.assertFalse((site_dir / "providers" / "alpha").exists())

    def test_expired_not_active(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_path = tmp_path / "offers.json"
            site_dir = tmp_path / "site"
            data_path.write_text(json.dumps(payload), encoding="utf-8")
            builder.build(
                config_path=FIXTURES / "site.ilang",
                data_path=data_path,
                site_dir=site_dir,
            )
            index = (site_dir / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("Old coupon", index)
            deal = (site_dir / "deals" / "old1" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Expired", deal)
            self.assertNotIn("https://schema.org/InStock", deal)

    def test_missing_valid_until_ok(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_path = tmp_path / "offers.json"
            site_dir = tmp_path / "site"
            data_path.write_text(json.dumps(payload), encoding="utf-8")
            builder.build(
                config_path=FIXTURES / "site.ilang",
                data_path=data_path,
                site_dir=site_dir,
            )
            deal = (site_dir / "deals" / "alpha1" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("priceValidUntil", deal)
            self.assertIn("9", deal)

    def test_jsonld_price_gate(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_path = tmp_path / "offers.json"
            site_dir = tmp_path / "site"
            data_path.write_text(json.dumps(payload), encoding="utf-8")
            builder.build(
                config_path=FIXTURES / "site.ilang",
                data_path=data_path,
                site_dir=site_dir,
            )
            priced = (site_dir / "deals" / "alpha1" / "index.html").read_text(encoding="utf-8")
            unpriced = (site_dir / "deals" / "beta1" / "index.html").read_text(encoding="utf-8")
            self.assertIn("priceCurrency", priced)
            self.assertNotIn("priceCurrency", unpriced)

    def test_canonical_self(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_path = tmp_path / "offers.json"
            site_dir = tmp_path / "site"
            data_path.write_text(json.dumps(payload), encoding="utf-8")
            builder.build(
                config_path=FIXTURES / "site.ilang",
                data_path=data_path,
                site_dir=site_dir,
            )
            index = (site_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn('rel="canonical" href="https://example.test/"', index)
            deal = (site_dir / "deals" / "alpha1" / "index.html").read_text(encoding="utf-8")
            self.assertIn('rel="canonical" href="https://example.test/deals/alpha1/"', deal)

    def test_sitemap_lastmod(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_path = tmp_path / "offers.json"
            site_dir = tmp_path / "site"
            data_path.write_text(json.dumps(payload), encoding="utf-8")
            builder.build(
                config_path=FIXTURES / "site.ilang",
                data_path=data_path,
                site_dir=site_dir,
            )
            sm = (site_dir / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("<lastmod>2026-09-09</lastmod>", sm)
            self.assertIn("https://example.test/deals/alpha1/", sm)

    def test_bare_link_without_affiliate(self) -> None:
        payload = self._payload()
        payload["offers"] = [payload["offers"][0]]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_path = tmp_path / "offers.json"
            site_dir = tmp_path / "site"
            data_path.write_text(json.dumps(payload), encoding="utf-8")
            builder.build(
                config_path=FIXTURES / "site.ilang",
                data_path=data_path,
                site_dir=site_dir,
            )
            deal = (site_dir / "deals" / "alpha1" / "index.html").read_text(encoding="utf-8")
            self.assertIn("https://alpha.example/pricing", deal)
            self.assertNotIn("rel=\"sponsored", deal)

    def test_affiliate_gets_sponsored(self) -> None:
        payload = self._payload()
        payload["offers"] = [payload["offers"][1]]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_path = tmp_path / "offers.json"
            site_dir = tmp_path / "site"
            data_path.write_text(json.dumps(payload), encoding="utf-8")
            builder.build(
                config_path=FIXTURES / "site.ilang",
                data_path=data_path,
                site_dir=site_dir,
            )
            deal = (site_dir / "deals" / "beta1" / "index.html").read_text(encoding="utf-8")
            self.assertIn("https://aff.example/beta", deal)
            self.assertIn('rel="sponsored', deal)


class SourceHonestyTests(unittest.TestCase):
    def test_no_hardcoded_provider_list(self) -> None:
        scraper = (ROOT / "scraper.py").read_text(encoding="utf-8")
        build_src = (ROOT / "build.py").read_text(encoding="utf-8")
        for name in ("DigitalOcean", "Contabo", "Hostinger", "OVHcloud", "Hetzner"):
            self.assertNotIn(name, scraper)
            self.assertNotIn(name, build_src)

    def test_workflow_cron(self) -> None:
        text = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "0 */6 * * *"', text)
        self.assertIn("python scraper.py", text)
        self.assertIn("python build.py", text)
        self.assertIn("wrangler@4 pages deploy site", text)
        self.assertIn("vps-deals-promo-radar", text)


if __name__ == "__main__":
    unittest.main()
