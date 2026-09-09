# ::ILANG
# [TYPE:code][FILE:scraper.py]
# ::STATE{role:fetch public provider pages listed in site.ilang}
# ::BOUNDARY{never:invent offers, prices, or commissions; never bypass robots}

"""Fetch official pages and write data/offers.json. Stdlib only."""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import hashlib
import json
import re
import ssl
import xml.etree.ElementTree as ET

from ilang_site import ROOT, load_site_config, slugify

USER_AGENT = (
    "VPSDealsPromoRadar/1.0 "
    "(+https://github.com/muke1838-cloud/vps-deals-promo-radar; "
    "public sitemap/feed/pricing pages only)"
)
TIMEOUT = 25
MAX_BYTES = 1_000_000
SITEMAP_FOLLOW_LIMIT = 8
DATA_PATH = ROOT / "data" / "offers.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    return ctx


class _HTMLExtract(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_ld = False
        self._in_title = False
        self._ld_buf: list[str] = []
        self.jsonld: list[str] = []
        self.title = ""
        self.canonical = ""
        self.meta_price: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script" and ad.get("type", "").lower() == "application/ld+json":
            self._in_ld = True
            self._ld_buf = []
        elif tag == "title":
            self._in_title = True
        elif tag == "link" and ad.get("rel", "").lower() == "canonical":
            self.canonical = ad.get("href", "").strip()
        elif tag == "meta":
            prop = (ad.get("property") or ad.get("name") or "").lower()
            content = ad.get("content", "").strip()
            if prop in {"product:price:amount", "og:price:amount"} and content:
                self.meta_price["amount"] = content
            if prop in {"product:price:currency", "og:price:currency"} and content:
                self.meta_price["currency"] = content

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ld:
            blob = "".join(self._ld_buf).strip()
            if blob:
                self.jsonld.append(blob)
            self._in_ld = False
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_ld:
            self._ld_buf.append(data)
        if self._in_title:
            self.title += data


def _types(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _walk(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_walk(item))
        return found
    if not isinstance(node, dict):
        return found
    types = _types(node.get("@type"))
    if any(t in {"Offer", "AggregateOffer", "Product", "Service"} for t in types):
        found.append(node)
    for key in ("@graph", "offers", "itemListElement", "itemOffered", "hasOfferCatalog"):
        if key in node:
            found.extend(_walk(node[key]))
    return found


def _clean_price(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = format(value, "f").rstrip("0").rstrip(".")
        return text or None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return match.group(0)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("@id") or value.get("url"))
    if isinstance(value, list):
        for item in value:
            got = _text(item)
            if got:
                return got
        return None
    text = str(value).strip()
    return text or None


def _abs(url: str | None, base: str) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url or url.startswith("{"):
        return None
    return urljoin(base, url)


def offer_id(provider: str, title: str, url: str, currency: str | None, price: str | None) -> str:
    raw = "|".join([provider, title, url, currency or "", price or ""])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def parse_jsonld_offers(
    html: str, source_url: str, provider: str, fetched_at: str
) -> list[dict[str, Any]]:
    parser = _HTMLExtract()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass

    offers: list[dict[str, Any]] = []
    for blob in parser.jsonld:
        blob = blob.replace("/*<![CDATA[*/", "").replace("/*]]>*/", "")
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            types = _types(node.get("@type"))
            product_name = None
            if any(t in {"Product", "Service"} for t in types):
                product_name = _text(node.get("name"))
                nested = node.get("offers")
                if nested is None:
                    if product_name:
                        offers.append(
                            _make_offer(
                                provider=provider,
                                title=product_name,
                                source_url=source_url,
                                offer_url=_abs(_text(node.get("url")), source_url)
                                or source_url,
                                fetched_at=fetched_at,
                                method="jsonld-product",
                            )
                        )
                    continue
                for offer_node in _walk(nested):
                    offers.extend(
                        _offers_from_offer_node(
                            offer_node,
                            provider,
                            source_url,
                            fetched_at,
                            fallback_title=product_name,
                        )
                    )
            elif any(t in {"Offer", "AggregateOffer"} for t in types):
                offers.extend(
                    _offers_from_offer_node(
                        node, provider, source_url, fetched_at, fallback_title=None
                    )
                )

    if parser.meta_price.get("amount"):
        price = _clean_price(parser.meta_price["amount"])
        currency = parser.meta_price.get("currency")
        title = " ".join(parser.title.split()) or provider
        offers.append(
            _make_offer(
                provider=provider,
                title=title,
                source_url=source_url,
                offer_url=parser.canonical or source_url,
                fetched_at=fetched_at,
                method="meta-price",
                price=price,
                currency=currency.upper() if currency else None,
            )
        )
    return _dedupe(offers)


def _offers_from_offer_node(
    node: dict[str, Any],
    provider: str,
    source_url: str,
    fetched_at: str,
    fallback_title: str | None,
) -> list[dict[str, Any]]:
    types = _types(node.get("@type"))
    title = (
        _text(node.get("name"))
        or fallback_title
        or _text(node.get("itemOffered"))
        or provider
    )
    url = (
        _abs(_text(node.get("url")), source_url)
        or _abs(_text(node.get("offerurl")), source_url)
        or source_url
    )
    valid_until = _text(node.get("priceValidUntil") or node.get("validThrough"))
    availability = _text(node.get("availability"))
    method = "jsonld-aggregateoffer" if "AggregateOffer" in types else "jsonld-offer"
    out: list[dict[str, Any]] = []
    if "AggregateOffer" in types:
        price = _clean_price(node.get("lowPrice") or node.get("price"))
        high = _clean_price(node.get("highPrice"))
        currency = _text(node.get("priceCurrency"))
        item = _make_offer(
            provider=provider,
            title=title,
            source_url=source_url,
            offer_url=url,
            fetched_at=fetched_at,
            method=method,
            price=price,
            currency=currency.upper() if currency else None,
            valid_until=valid_until,
            availability=availability,
        )
        if high:
            item["high_price"] = high
        if node.get("offerCount") is not None:
            item["offer_count"] = str(node.get("offerCount"))
        item["price_kind"] = "from" if price else None
        if item.get("price_kind") is None:
            item.pop("price_kind", None)
        out.append(item)
        return out

    price = _clean_price(node.get("price"))
    currency = _text(node.get("priceCurrency"))
    out.append(
        _make_offer(
            provider=provider,
            title=title,
            source_url=source_url,
            offer_url=url,
            fetched_at=fetched_at,
            method=method,
            price=price,
            currency=currency.upper() if currency else None,
            valid_until=valid_until,
            availability=availability,
        )
    )
    return out


def _make_offer(
    *,
    provider: str,
    title: str,
    source_url: str,
    offer_url: str,
    fetched_at: str,
    method: str,
    price: str | None = None,
    currency: str | None = None,
    valid_until: str | None = None,
    availability: str | None = None,
) -> dict[str, Any]:
    parsed_source = urlparse(source_url)
    parsed_offer = urlparse(offer_url)
    if (
        parsed_offer.path in {"", "/"}
        and parsed_source.path not in {"", "/"}
        and parsed_offer.netloc == parsed_source.netloc
    ):
        offer_url = source_url
    item: dict[str, Any] = {
        "id": offer_id(provider, title, offer_url, currency, price),
        "provider": provider,
        "provider_slug": slugify(provider),
        "title": title,
        "offer_url": offer_url,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "extract_method": method,
        "status": "active",
    }
    if price is not None:
        item["price"] = price
    if currency:
        item["currency"] = currency
    if valid_until:
        item["valid_until"] = valid_until
    if availability:
        item["availability"] = availability.split("/")[-1]
    return item


def _dedupe(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in offers:
        key = item["id"]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def parse_feed(xml_text: str, source_url: str, provider: str, fetched_at: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    offers: list[dict[str, Any]] = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = list(root.findall("channel/item"))
    if not items:
        items = list(root.findall("atom:entry", ns)) + list(root.findall("entry"))
    for node in items:
        title = (node.findtext("title") or node.findtext("atom:title", default="", namespaces=ns) or "").strip()
        link = node.findtext("link") or ""
        if not link:
            atom_link = node.find("atom:link", ns)
            if atom_link is not None:
                link = atom_link.attrib.get("href", "")
            elif node.find("link") is not None:
                link = node.find("link").attrib.get("href", "")
        link = _abs(link, source_url) or source_url
        if not title:
            continue
        offers.append(
            _make_offer(
                provider=provider,
                title=title,
                source_url=source_url,
                offer_url=link,
                fetched_at=fetched_at,
                method="feed",
            )
        )
    return _dedupe(offers)


def parse_sitemap_locs(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    locs: list[str] = []
    for node in root.iter():
        if node.tag.endswith("loc") and node.text:
            locs.append(node.text.strip())
    return locs


def robots_allows(home_url: str, target: str) -> tuple[bool, str]:
    parsed = urlparse(home_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    try:
        fetched = http_get(robots_url)
        if fetched["status"] != 200 or not fetched["text"]:
            return True, "robots_missing_or_error_fail_open_for_public_docs"
        rp.parse(fetched["text"].splitlines())
        allowed = rp.can_fetch(USER_AGENT, target)
        return allowed, robots_url
    except Exception as exc:
        return True, f"robots_error:{type(exc).__name__}"


def http_get(url: str) -> dict[str, Any]:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml,application/rss+xml,text/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=TIMEOUT, context=ssl_context()) as resp:
            raw = resp.read(MAX_BYTES + 1)
            truncated = len(raw) > MAX_BYTES
            raw = raw[:MAX_BYTES]
            charset = resp.headers.get_content_charset() or "utf-8"
            text = raw.decode(charset, "replace")
            return {
                "status": getattr(resp, "status", 200),
                "url": resp.geturl(),
                "content_type": resp.headers.get("content-type", ""),
                "text": text,
                "truncated": truncated,
                "error": None,
            }
    except HTTPError as exc:
        return {
            "status": exc.code,
            "url": url,
            "content_type": "",
            "text": "",
            "truncated": False,
            "error": str(exc.reason),
        }
    except URLError as exc:
        return {
            "status": 0,
            "url": url,
            "content_type": "",
            "text": "",
            "truncated": False,
            "error": str(exc.reason),
        }


def looks_like_xml(content_type: str, text: str, url: str) -> bool:
    if "xml" in content_type.lower() or "rss" in content_type.lower() or "atom" in content_type.lower():
        return True
    path = urlparse(url).path.lower()
    if path.endswith(".xml") or path.endswith("/feed") or path.endswith("/rss"):
        return True
    start = text.lstrip()[:80].lower()
    return start.startswith("<?xml") or start.startswith("<rss") or start.startswith("<feed") or "<urlset" in start


def interesting_sitemap_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(
        token in path
        for token in (
            "price",
            "pricing",
            "promo",
            "deal",
            "coupon",
            "vps",
            "cloud",
            "offer",
            "sale",
        )
    )


def parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime(int(text[0:4]), int(text[5:7]), int(text[8:10]), tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def mark_expired(offer: dict[str, Any], now: datetime) -> dict[str, Any]:
    parsed = parse_timestamp(offer.get("valid_until"))
    if parsed is None:
        return offer
    if parsed < now:
        offer = dict(offer)
        offer["status"] = "expired"
    return offer


def scrape_provider(provider: dict[str, Any], now_iso: str) -> dict[str, Any]:
    source = provider["source_url"]
    allowed, robots_note = robots_allows(provider["home_url"], source)
    record: dict[str, Any] = {
        "name": provider["name"],
        "slug": provider["slug"],
        "home_url": provider["home_url"],
        "source_url": source,
        "affiliate_url": provider.get("affiliate_url"),
        "robots_allowed": allowed,
        "robots_note": robots_note,
        "status": "ok",
        "http_status": None,
        "final_url": None,
        "error": None,
        "offer_count": 0,
    }
    if not allowed:
        record["status"] = "skipped_robots"
        record["error"] = "robots.txt disallows this user-agent for the source URL"
        return {"record": record, "offers": []}

    fetched = http_get(source)
    record["http_status"] = fetched["status"]
    record["final_url"] = fetched["url"]
    record["error"] = fetched["error"]
    if fetched["status"] != 200 or not fetched["text"]:
        record["status"] = "fetch_error"
        return {"record": record, "offers": []}

    text = fetched["text"]
    ctype = fetched["content_type"]
    offers: list[dict[str, Any]] = []
    if looks_like_xml(ctype, text, fetched["url"]):
        if "<urlset" in text or "<sitemapindex" in text:
            locs = [
                loc
                for loc in parse_sitemap_locs(text)
                if interesting_sitemap_url(loc)
                and urlparse(loc).netloc == urlparse(provider["home_url"]).netloc
            ][:SITEMAP_FOLLOW_LIMIT]
            for loc in locs:
                page = http_get(loc)
                if page["status"] != 200 or not page["text"]:
                    continue
                if looks_like_xml(page["content_type"], page["text"], page["url"]):
                    offers.extend(parse_feed(page["text"], loc, provider["name"], now_iso))
                else:
                    offers.extend(
                        parse_jsonld_offers(page["text"], loc, provider["name"], now_iso)
                    )
        else:
            offers.extend(parse_feed(text, source, provider["name"], now_iso))
    else:
        offers.extend(parse_jsonld_offers(text, source, provider["name"], now_iso))

    now = datetime.now(timezone.utc)
    offers = [mark_expired(item, now) for item in offers]
    for item in offers:
        if provider.get("affiliate_url"):
            item["affiliate_url"] = provider["affiliate_url"]
    record["offer_count"] = len(offers)
    if not offers:
        record["status"] = "ok_no_structured_offers"
    return {"record": record, "offers": offers}


def scrape(config_path: Path | None = None) -> dict[str, Any]:
    config = load_site_config(config_path)
    now_iso = utc_now()
    provider_records = []
    all_offers: list[dict[str, Any]] = []
    for provider in config["providers"]:
        result = scrape_provider(provider, now_iso)
        provider_records.append(result["record"])
        all_offers.extend(result["offers"])
    try:
        config_source = str(Path(config["source"]).resolve().relative_to(ROOT))
    except Exception:
        config_source = ".ilang/site.ilang"
    payload = {
        "generated_at": now_iso,
        "locale": config["site"].get("locale", "en-US"),
        "brand": config["site"]["brand"],
        "config_source": config_source,
        "user_agent": USER_AGENT,
        "providers": provider_records,
        "offers": _dedupe(all_offers),
    }
    return payload


def write_offers(payload: dict[str, Any], path: Path | None = None) -> Path:
    out = path or DATA_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    payload = scrape()
    path = write_offers(payload)
    priced = sum(1 for item in payload["offers"] if "price" in item)
    print(
        f"wrote {path} providers={len(payload['providers'])} "
        f"offers={len(payload['offers'])} priced={priced}"
    )


if __name__ == "__main__":
    main()
