# ::ILANG
# [TYPE:code][FILE:ilang_site.py]
# ::STATE{role:parse .ilang/site.ilang as plain text config}
# ::BOUNDARY{never:invent providers, prices, or commissions}

"""Parse .ilang/site.ilang. This is config, not an I-Lang runtime."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_ILANG = ROOT / ".ilang" / "site.ilang"

_STATE_RE = re.compile(
    r"::STATE\{@SITE,\s*(.*?)\}",
    re.DOTALL,
)
_KV_RE = re.compile(r"(\w+)\s*:\s*([^,\}]+)")
_MODULE_RE = re.compile(
    r"::MODULE\{([A-Z0-9_]+)(?:\|title:([^\}]*))?\}(.*?)(?=::MODULE\{|::RULE\{|::BOUNDARY\{|\Z)",
    re.DOTALL,
)


def load_site_config(path: Path | None = None) -> dict[str, Any]:
    ilang_path = Path(path) if path else DEFAULT_ILANG
    text = ilang_path.read_text(encoding="utf-8")
    return parse_site_ilang(text, source=str(ilang_path))


def parse_site_ilang(text: str, source: str = "") -> dict[str, Any]:
    site: dict[str, str] = {
        "brand": "vps-deals",
        "niche": "vps-hosting",
        "domain": "",
        "locale": "en-US",
        "display_brand": "",
    }
    state_m = _STATE_RE.search(text)
    if state_m:
        for key, raw in _KV_RE.findall(state_m.group(1)):
            site[key.strip()] = raw.strip()
    if not site.get("display_brand"):
        site["display_brand"] = site["brand"]

    modules: dict[str, str] = {}
    for name, _title, body in _MODULE_RE.findall(text):
        modules[name] = body.strip()

    providers = []
    for line in modules.get("PROVIDERS", "").splitlines():
        line = line.strip()
        if not line or line.startswith("<") or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        affiliate = parts[3] if len(parts) > 3 else ""
        providers.append(
            {
                "name": parts[0],
                "home_url": parts[1],
                "source_url": parts[2],
                "affiliate_url": affiliate or None,
                "slug": slugify(parts[0]),
            }
        )

    fields = [
        tok
        for tok in re.split(r"[\s,]+", modules.get("FIELDS", ""))
        if tok
    ]
    render: dict[str, str] = {}
    for line in modules.get("RENDER", "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        render[key.strip()] = value.strip()

    return {
        "site": site,
        "providers": providers,
        "fields": fields or [
            "title",
            "price",
            "currency",
            "offer_url",
            "valid_until",
            "source_url",
            "fetched_at",
        ],
        "render": render,
        "source": source,
        "raw": text,
    }


def slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "item"


def public_origin(site: dict[str, str]) -> str:
    domain = (site.get("domain") or "").strip().rstrip("/")
    if not domain:
        return ""
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain
    return "https://" + domain
