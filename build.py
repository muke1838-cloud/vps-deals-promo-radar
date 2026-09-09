# ::ILANG
# [TYPE:code][FILE:build.py]
# ::STATE{role:render site/ from offers.json and site.ilang}
# ::BOUNDARY{never:invent prices or commissions; never emit schema price without source price}

"""Render the static site into site/. Stdlib only."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import json
import re
import shutil

from ilang_site import ROOT, load_site_config, public_origin, slugify

DATA_PATH = ROOT / "data" / "offers.json"
SITE_DIR = ROOT / "site"
TEMPLATE_DIR = ROOT / "templates"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"generated_at": None, "offers": [], "providers": []}
    return json.loads(path.read_text(encoding="utf-8"))


def origin_with_slash(origin: str) -> str:
    return origin.rstrip("/") + "/"


def page_url(origin: str, path: str) -> str:
    return urljoin(origin_with_slash(origin), path.lstrip("/"))


def parse_when(raw: str | None) -> datetime | None:
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


def is_expired(offer: dict[str, Any], now: datetime) -> bool:
    if offer.get("status") == "expired":
        return True
    until = parse_when(offer.get("valid_until"))
    return bool(until and until < now)


def month_label(raw: str | None) -> str:
    dt = parse_when(raw)
    if not dt:
        return ""
    return dt.strftime("%B %Y")


def preferred_currency(config: dict[str, Any]) -> str:
    return (config.get("render") or {}).get("locale_currency") or "USD"


def outbound(offer: dict[str, Any], provider_cfg: dict[str, Any] | None) -> tuple[str, bool]:
    affiliate = offer.get("affiliate_url") or (provider_cfg or {}).get("affiliate_url")
    if affiliate:
        return affiliate, True
    return offer.get("offer_url") or (provider_cfg or {}).get("source_url") or "#", False


def provider_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["slug"]: p for p in config["providers"]}


def active_offers(offers: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    return [o for o in offers if not is_expired(o, now)]


def filter_offers_for_site(
    offers: list[dict[str, Any]], allowed_slugs: set[str]
) -> list[dict[str, Any]]:
    return [o for o in offers if o.get("provider_slug") in allowed_slugs]


def pick_display_offers(
    offers: list[dict[str, Any]], currency: str
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for offer in offers:
        key = (offer.get("provider_slug", ""), offer.get("title", ""))
        grouped.setdefault(key, []).append(offer)
    chosen: list[dict[str, Any]] = []
    for items in grouped.values():
        priced = [i for i in items if i.get("price") and i.get("currency") == currency]
        if priced:
            chosen.extend(priced)
            continue
        any_priced = [i for i in items if i.get("price")]
        if any_priced:
            chosen.extend(any_priced)
            continue
        chosen.append(items[0])
    return chosen


def render_template(name: str, mapping: dict[str, str]) -> str:
    text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
    for key, value in mapping.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def json_ld(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def offer_schema(offer: dict[str, Any], deal_url: str) -> dict[str, Any] | None:
    if "price" not in offer or not offer.get("currency"):
        return None
    types = "AggregateOffer" if offer.get("high_price") or offer.get("price_kind") == "from" else "Offer"
    node: dict[str, Any] = {
        "@type": types,
        "url": offer.get("offer_url") or deal_url,
        "priceCurrency": offer["currency"],
        "availability": "https://schema.org/Discontinued"
        if offer.get("status") == "expired"
        else "https://schema.org/InStock",
    }
    if types == "AggregateOffer":
        node["lowPrice"] = offer["price"]
        if offer.get("high_price"):
            node["highPrice"] = offer["high_price"]
        if offer.get("offer_count"):
            node["offerCount"] = offer["offer_count"]
    else:
        node["price"] = offer["price"]
    until = offer.get("valid_until")
    if until and offer.get("status") != "expired":
        node["priceValidUntil"] = until
    return node


def breadcrumbs(origin: str, items: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i,
                "name": name,
                "item": page_url(origin, path),
            }
            for i, (name, path) in enumerate(items, start=1)
        ],
    }


def layout_head(
    *,
    title: str,
    description: str,
    canonical: str,
    json_ld_blocks: list[dict[str, Any]],
    extra: str = "",
) -> str:
    ld = "\n".join(
        f'<script type="application/ld+json">{escape_json_ld(block)}</script>'
        for block in json_ld_blocks
    )
    return f"""<!DOCTYPE html>
<html lang="en-US">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
<link rel="canonical" href="{escape(canonical)}">
<link rel="alternate" hreflang="en" href="{escape(canonical)}">
<link rel="alternate" hreflang="x-default" href="{escape(canonical)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(description)}">
<meta property="og:url" content="{escape(canonical)}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{escape(title)}">
<meta name="twitter:description" content="{escape(description)}">
<link rel="stylesheet" href="/assets/style.css">
{ld}
{extra}
</head>
"""


def escape_json_ld(block: dict[str, Any]) -> str:
    return json_ld(block).replace("<", "\\u003c")


def nav(brand: str) -> str:
    return f"""<header class="site-header">
  <a class="brand" href="/">{escape(brand)}</a>
  <nav>
    <a href="/">Deals</a>
    <a href="/compare/">Compare</a>
    <a href="/about/">About the data</a>
  </nav>
</header>
"""


def footer(brand: str, generated_at: str) -> str:
    return f"""<footer class="site-footer">
  <p>{escape(brand)} lists publicly posted VPS pricing and promotions. We do not invent prices or commissions. Confirm every number on the provider page before you buy.</p>
  <p>Snapshot generated {escape(generated_at or "unknown")}. Site rules live in <code>.ilang/site.ilang</code>.</p>
</footer>
"""


def price_label(offer: dict[str, Any]) -> str:
    if "price" not in offer or not offer.get("currency"):
        return "Price not in source snapshot"
    prefix = "from " if offer.get("price_kind") == "from" or offer.get("high_price") else ""
    high = f"–{offer['high_price']}" if offer.get("high_price") else ""
    return f"{prefix}{offer['price']}{high} {offer['currency']}"


def write_bytes(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def copy_assets(out_dir: Path) -> None:
    dest = out_dir / "assets"
    dest.mkdir(parents=True, exist_ok=True)
    src = TEMPLATE_DIR / "style.css"
    shutil.copyfile(src, dest / "style.css")


def build(config_path: Path | None = None, data_path: Path | None = None, site_dir: Path | None = None) -> dict[str, Any]:
    config = load_site_config(config_path)
    data = load_json(data_path or DATA_PATH)
    out_dir = site_dir or SITE_DIR
    if out_dir.exists():
        for child in out_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    origin = public_origin(config["site"]) or "https://vps-deals-promo-radar.pages.dev"
    brand = config["site"].get("display_brand") or config["site"]["brand"]
    now = datetime.now(timezone.utc)
    allowed = {p["slug"] for p in config["providers"]}
    pmap = provider_map(config)
    offers = filter_offers_for_site(data.get("offers") or [], allowed)
    for offer in offers:
        if is_expired(offer, now):
            offer["status"] = "expired"
    live = pick_display_offers(active_offers(offers, now), preferred_currency(config))
    generated_at = data.get("generated_at") or utc_stamp()
    month = month_label(generated_at) or month_label(utc_stamp())
    fetch_by_slug = {p.get("slug"): p for p in data.get("providers") or []}

    copy_assets(out_dir)
    built_paths: list[tuple[str, str]] = []

    index_html = render_index(
        brand=brand,
        origin=origin,
        month=month,
        generated_at=generated_at,
        config=config,
        live=live,
        fetch_by_slug=fetch_by_slug,
        pmap=pmap,
    )
    write_bytes(out_dir / "index.html", index_html)
    built_paths.append(("/", generated_at))

    compare_html = render_compare(
        brand=brand,
        origin=origin,
        month=month,
        generated_at=generated_at,
        live=live,
        config=config,
        pmap=pmap,
        fetch_by_slug=fetch_by_slug,
    )
    write_bytes(out_dir / "compare" / "index.html", compare_html)
    built_paths.append(("/compare/", generated_at))

    about_html = render_about(brand, origin, generated_at, config, data)
    write_bytes(out_dir / "about" / "index.html", about_html)
    built_paths.append(("/about/", generated_at))

    for provider in config["providers"]:
        slug = provider["slug"]
        group = [o for o in offers if o.get("provider_slug") == slug]
        html = render_provider(
            brand=brand,
            origin=origin,
            month=month,
            generated_at=generated_at,
            provider=provider,
            offers=group,
            fetch=fetch_by_slug.get(slug) or {},
            pmap=pmap,
        )
        write_bytes(out_dir / "providers" / slug / "index.html", html)
        latest = max((o.get("fetched_at") or generated_at for o in group), default=generated_at)
        built_paths.append((f"/providers/{slug}/", latest))
        for offer in group:
            deal_html = render_deal(
                brand=brand,
                origin=origin,
                month=month,
                generated_at=generated_at,
                provider=provider,
                offer=offer,
            )
            write_bytes(out_dir / "deals" / offer["id"] / "index.html", deal_html)
            built_paths.append((f"/deals/{offer['id']}/", offer.get("fetched_at") or generated_at))

    write_bytes(out_dir / "robots.txt", robots_txt(origin))
    write_bytes(out_dir / "sitemap.xml", sitemap_xml(origin, built_paths))
    write_bytes(out_dir / "404.html", render_404(brand, origin))
    return {"pages": len(built_paths), "offers": len(offers), "active": len(live), "origin": origin}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def robots_txt(origin: str) -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {page_url(origin, '/sitemap.xml')}\n"


def sitemap_xml(origin: str, paths: list[tuple[str, str]]) -> str:
    rows = []
    seen = set()
    for path, lastmod in paths:
        if path in seen:
            continue
        seen.add(path)
        lm = (lastmod or "")[:10]
        loc = page_url(origin, path)
        rows.append(
            f"  <url><loc>{escape(loc)}</loc>"
            + (f"<lastmod>{escape(lm)}</lastmod>" if lm else "")
            + "</url>"
        )
    body = "\n".join(rows)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n"
    )


def offer_card(offer: dict[str, Any], origin: str, provider_cfg: dict[str, Any] | None) -> str:
    href, sponsored = outbound(offer, provider_cfg)
    rel = ' rel="sponsored noopener noreferrer"' if sponsored else ' rel="noopener noreferrer"'
    expired = ' expired' if offer.get("status") == "expired" else ""
    deal_href = f"/deals/{escape(offer['id'])}/"
    return f"""<article class="card{expired}">
  <p class="kicker">{escape(offer.get("provider") or "")}</p>
  <h2><a href="{deal_href}">{escape(offer.get("title") or "")}</a></h2>
  <p class="price">{escape(price_label(offer))}</p>
  <p class="meta">Source snapshot {escape((offer.get("fetched_at") or "")[:10])} · <a href="{escape(offer.get("source_url") or href)}">source page</a></p>
  <p><a class="btn" href="{escape(href)}"{rel}>Open provider</a></p>
</article>
"""


def render_index(**kw: Any) -> str:
    brand = kw["brand"]
    origin = kw["origin"]
    month = kw["month"]
    generated_at = kw["generated_at"]
    config = kw["config"]
    live = kw["live"]
    fetch_by_slug = kw["fetch_by_slug"]
    pmap = kw["pmap"]
    canonical = page_url(origin, "/")
    title = f"{brand}: public VPS deals and pricing snapshots ({month})"
    description = (
        f"Public VPS pricing and promotions collected from official provider pages, {month}. "
        "Missing prices stay missing. No estimated commissions."
    )
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": title,
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i,
                "url": page_url(origin, f"/deals/{offer['id']}/"),
            }
            for i, offer in enumerate(live, start=1)
        ],
    }
    faq = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "Where do the prices come from?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "From public official pricing or promotion pages listed in .ilang/site.ilang. The scraper stores source_url and fetched_at for every row.",
                },
            },
            {
                "@type": "Question",
                "name": "Why is a provider missing a price?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "If the public HTML did not include a machine-readable price, the field is omitted. We do not estimate it.",
                },
            },
            {
                "@type": "Question",
                "name": "Do you publish affiliate commissions?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "No. Commission amounts are never invented. Empty affiliate slots use the provider URL.",
                },
            },
        ],
    }
    cards = "\n".join(offer_card(o, origin, pmap.get(o.get("provider_slug"))) for o in live) or (
        "<p>No structured offers in the latest snapshot. Provider pages still link to official sources.</p>"
    )
    provider_rows = []
    for provider in config["providers"]:
        fetch = fetch_by_slug.get(provider["slug"]) or {}
        status = fetch.get("status") or "not_fetched"
        http_status = fetch.get("http_status")
        extra = f"HTTP {http_status}" if http_status else status
        provider_rows.append(
            f'<li><a href="/providers/{escape(provider["slug"])}/">{escape(provider["name"])}</a> · {escape(str(extra))}</li>'
        )
    main = render_template(
        "index.html",
        {
            "h1": escape(brand),
            "lede": (
                "Public VPS pricing snapshots from official pages. "
                f"{escape(month)}. If a price was not on the page, it is not on this site."
            ),
            "cards": cards,
            "provider_rows": "".join(provider_rows),
        },
    )
    body = f"<body>\n{nav(brand)}\n{main}\n{footer(brand, generated_at)}\n</body></html>\n"
    head = layout_head(
        title=title,
        description=description,
        canonical=canonical,
        json_ld_blocks=[
            {"@context": "https://schema.org", **breadcrumbs(origin, [(brand, "/")])},
            item_list,
            faq,
        ],
    )
    return head + body


def render_compare(**kw: Any) -> str:
    brand = kw["brand"]
    origin = kw["origin"]
    month = kw["month"]
    generated_at = kw["generated_at"]
    live = kw["live"]
    config = kw["config"]
    pmap = kw["pmap"]
    canonical = page_url(origin, "/compare/")
    title = f"Compare VPS snapshots — {brand} ({month})"
    description = f"Side-by-side public VPS snapshot for {month}. Prices appear only when the source page published them."
    rows = []
    item_list_el = []
    position = 1
    for provider in config["providers"]:
        group = [o for o in live if o.get("provider_slug") == provider["slug"]]
        priced = [o for o in group if "price" in o]
        if priced:
            best = sorted(priced, key=lambda o: float(o["price"]))[0]
            label = price_label(best)
            title_cell = best.get("title") or provider["name"]
            href = f"/deals/{best['id']}/"
        elif group:
            best = group[0]
            label = price_label(best)
            title_cell = best.get("title") or provider["name"]
            href = f"/deals/{best['id']}/"
        else:
            label = "No structured offer this run"
            title_cell = "Official page"
            href = f"/providers/{provider['slug']}/"
        rows.append(
            "<tr>"
            f"<td><a href=\"/providers/{escape(provider['slug'])}/\">{escape(provider['name'])}</a></td>"
            f"<td><a href=\"{escape(href)}\">{escape(title_cell)}</a></td>"
            f"<td>{escape(label)}</td>"
            "</tr>"
        )
        item_list_el.append(
            {"@type": "ListItem", "position": position, "url": page_url(origin, href)}
        )
        position += 1
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": title,
        "itemListElement": item_list_el,
    }
    head = layout_head(
        title=title,
        description=description,
        canonical=canonical,
        json_ld_blocks=[
            breadcrumbs(origin, [(brand, "/"), ("Compare", "/compare/")]),
            item_list,
        ],
    )
    main = render_template(
        "compare.html",
        {
            "h1": "Compare",
            "lede": "One row per configured provider. A blank price means the public page did not expose one in this snapshot.",
            "rows": "".join(rows),
        },
    )
    body = f"<body>\n{nav(brand)}\n{main}\n{footer(brand, generated_at)}\n</body></html>\n"
    return head + body


def render_about(brand: str, origin: str, generated_at: str, config: dict[str, Any], data: dict[str, Any]) -> str:
    canonical = page_url(origin, "/about/")
    title = f"About the data — {brand}"
    description = "How this site collects public VPS pricing. No invented prices or commissions."
    providers = "".join(
        f"<li>{escape(p['name'])} — <a href=\"{escape(p['source_url'])}\">{escape(p['source_url'])}</a></li>"
        for p in config["providers"]
    )
    head = layout_head(
        title=title,
        description=description,
        canonical=canonical,
        json_ld_blocks=[breadcrumbs(origin, [(brand, "/"), ("About", "/about/")])],
    )
    body = f"""<body>
{nav(brand)}
<main>
  <h1>About the data</h1>
  <p>This site is a static snapshot. A Python job reads <code>.ilang/site.ilang</code>, fetches only those official URLs, and writes <code>data/offers.json</code>. The builder never fills in a missing price.</p>
  <p>Last snapshot: {escape(data.get("generated_at") or generated_at or "not yet")}.</p>
  <h2>Current sources</h2>
  <ul>{providers}</ul>
  <p>Affiliate URLs stay empty until a real program link is added in site.ilang. Empty means the button goes to the provider.</p>
</main>
{footer(brand, generated_at)}
</body></html>
"""
    return head + body


def render_provider(**kw: Any) -> str:
    brand = kw["brand"]
    origin = kw["origin"]
    month = kw["month"]
    generated_at = kw["generated_at"]
    provider = kw["provider"]
    offers = kw["offers"]
    fetch = kw["fetch"]
    pmap = kw["pmap"]
    canonical = page_url(origin, f"/providers/{provider['slug']}/")
    title = f"{provider['name']} VPS snapshots — {brand} ({month})"
    description = f"Public {provider['name']} VPS offers copied from {provider['source_url']} in {month}."
    live = [o for o in offers if o.get("status") != "expired"]
    cards = "\n".join(offer_card(o, origin, provider) for o in live) or (
        f"<p>No machine-readable offer on the last fetch. Official page: "
        f"<a href=\"{escape(provider['source_url'])}\">{escape(provider['source_url'])}</a>. "
        f"Fetch status: {escape(str(fetch.get('status') or 'unknown'))}"
        f"{' HTTP ' + str(fetch.get('http_status')) if fetch.get('http_status') else ''}.</p>"
    )
    product: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": f"{provider['name']} VPS",
        "url": canonical,
        "provider": {"@type": "Organization", "name": provider["name"], "url": provider["home_url"]},
    }
    priced = [o for o in live if "price" in o and o.get("currency")]
    if priced:
        currencies = {o["currency"] for o in priced}
        if len(currencies) == 1:
            lows = [float(o["price"]) for o in priced]
            highs = [float(o.get("high_price") or o["price"]) for o in priced]
            product["offers"] = {
                "@type": "AggregateOffer",
                "priceCurrency": next(iter(currencies)),
                "lowPrice": format(min(lows), "f").rstrip("0").rstrip("."),
                "highPrice": format(max(highs), "f").rstrip("0").rstrip("."),
                "offerCount": str(len(priced)),
                "url": provider["source_url"],
            }
    item_list = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i,
                "url": page_url(origin, f"/deals/{o['id']}/"),
            }
            for i, o in enumerate(live, start=1)
        ],
    }
    head = layout_head(
        title=title,
        description=description,
        canonical=canonical,
        json_ld_blocks=[
            breadcrumbs(origin, [(brand, "/"), (provider["name"], f"/providers/{provider['slug']}/")]),
            product,
            item_list,
        ],
    )
    main = render_template(
        "provider.html",
        {
            "h1": escape(provider["name"]),
            "lede": (
                f'Official site: <a href="{escape(provider["home_url"])}">{escape(provider["home_url"])}</a>. '
                f'Crawl URL: <a href="{escape(provider["source_url"])}">{escape(provider["source_url"])}</a>.'
            ),
            "cards": cards,
        },
    )
    body = f"<body>\n{nav(brand)}\n{main}\n{footer(brand, generated_at)}\n</body></html>\n"
    return head + body


def render_deal(**kw: Any) -> str:
    brand = kw["brand"]
    origin = kw["origin"]
    month = kw["month"]
    generated_at = kw["generated_at"]
    provider = kw["provider"]
    offer = kw["offer"]
    canonical = page_url(origin, f"/deals/{offer['id']}/")
    price_txt = price_label(offer)
    title = f"{offer.get('title')} — {provider['name']} ({month})"
    if "price" in offer and offer.get("currency"):
        title = f"{provider['name']} {offer.get('title')} {price_txt} ({month})"
    description = (
        f"{offer.get('title')} listed from {offer.get('source_url')} at {offer.get('fetched_at')}. "
        f"{price_txt}."
    )
    href, sponsored = outbound(offer, provider)
    rel = ' rel="sponsored noopener noreferrer"' if sponsored else ' rel="noopener noreferrer"'
    schema_nodes: list[dict[str, Any]] = [
        breadcrumbs(
            origin,
            [
                (brand, "/"),
                (provider["name"], f"/providers/{provider['slug']}/"),
                (offer.get("title") or "Deal", f"/deals/{offer['id']}/"),
            ],
        )
    ]
    offer_node = offer_schema(offer, canonical)
    product = {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": offer.get("title"),
        "url": canonical,
        "provider": {"@type": "Organization", "name": provider["name"], "url": provider["home_url"]},
    }
    if offer_node and offer.get("status") != "expired":
        product["offers"] = offer_node
    schema_nodes.append(product)
    expired_banner = (
        '<p class="expired-flag">Expired according to valid_until. Do not treat this as a live offer.</p>'
        if offer.get("status") == "expired"
        else ""
    )
    fields = []
    for key in ("title", "price", "currency", "offer_url", "valid_until", "source_url", "fetched_at"):
        if key in offer:
            fields.append(f"<tr><th>{escape(key)}</th><td>{escape(str(offer[key]))}</td></tr>")
        elif key == "price":
            fields.append("<tr><th>price</th><td>omitted — not present in source</td></tr>")
    head = layout_head(
        title=title,
        description=description,
        canonical=canonical,
        json_ld_blocks=schema_nodes,
    )
    main = render_template(
        "deal.html",
        {
            "expired_banner": expired_banner,
            "kicker": f'<a href="/providers/{escape(provider["slug"])}/">{escape(provider["name"])}</a>',
            "h1": escape(offer.get("title") or ""),
            "price": escape(price_txt),
            "cta": f'<a class="btn" href="{escape(href)}"{rel}>Open provider</a>',
            "fields": "".join(fields),
            "meta": (
                f"Extract method: {escape(str(offer.get('extract_method') or 'unknown'))}. "
                "This page does not add numbers that were not in the source."
            ),
        },
    )
    body = f"<body>\n{nav(brand)}\n{main}\n{footer(brand, generated_at)}\n</body></html>\n"
    return head + body


def render_404(brand: str, origin: str) -> str:
    head = layout_head(
        title=f"Not found — {brand}",
        description="That URL is not in this snapshot.",
        canonical=page_url(origin, "/404.html"),
        json_ld_blocks=[],
    )
    return (
        head
        + f"<body>{nav(brand)}<main><h1>Not found</h1><p><a href=\"/\">Back to deals</a></p></main></body></html>"
    )


def main() -> None:
    stats = build()
    print(
        f"built site/ pages={stats['pages']} offers={stats['offers']} "
        f"active={stats['active']} origin={stats['origin']}"
    )


if __name__ == "__main__":
    main()
