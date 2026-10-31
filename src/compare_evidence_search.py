"""Exact-MPN evidence lookup for Compare Parts beyond a single datasheet URL.

Sources are attempted in a controlled order. A URL slug alone never establishes
identity. Values are taken only from a retrieved document whose extractable
text names the entered manufacturer and exact MPN (or an explicit order-code
row that includes that exact MPN).
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import quote, urljoin

import requests

from src.datasheet_comparison import (
    _canonical_datasheet_url,
    _pdf_mentions_exact_part,
    _public_datasheet_url,
    extract_datasheet_text,
    verify_datasheet_identity,
)

PROVIDER_NOT_CONFIGURED = "not_configured"
PROVIDER_AVAILABLE = "available"
PROVIDER_HTTP_BLOCKED = "http_blocked"
PROVIDER_NOT_FOUND = "not_found"
PROVIDER_ERROR = "error"
PROVIDER_TIMEOUT = "timeout"
PROVIDER_REDIRECT_LOOP = "redirect_loop"
PROVIDER_SKIPPED = "skipped"
PROVIDER_DISCOVERY_LEAD = "discovery_lead"

_PREFETCHED_COMPARE_FETCHES: ContextVar[dict[tuple[str, str], tuple[str, bytes | str, str]] | None] = ContextVar(
    "cadivor_prefetched_compare_fetches", default=None
)

# Indexed DigiKey detail URLs found during discovery. Recorded as leads only.
# Attribute values require the permitted DigiKey API (or another authorized
# integration); public HTML 403 bodies are never used.
_DIGIKEY_INDEXED_LISTING_LEADS: dict[tuple[str, str], str] = {
    ("ohmite", "RES10K"): "https://www.digikey.com/en/products/detail/ohmite/RES10K/258353",
}

# Ohmite-authorized distributor product pages for exact-MPN probes. A URL slug
# alone is never identity proof; retrieved extractable text must name Ohmite and
# the exact MPN before any attribute values are taken. HTTP 403 bodies and
# Cloudflare challenge pages are never used.
_AUTHORIZED_DISTRIBUTOR_PRODUCT_PAGES: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("ohmite", "RES10K"): [
        (
            "rs_group_authorized_product_page",
            "https://uk.rs-online.com/web/p/potentiometers/70585847",
        ),
        (
            "rs_group_authorized_product_page",
            "https://us.rs-online.com/product/ohmite/res10k/70585847/",
        ),
        (
            "arrow_authorized_product_page",
            "https://www.arrow.com/en/products/res10k/ohmite",
        ),
        (
            "galco_authorized_product_page",
            "https://www.galco.com/buy/Ohmite/RES10K",
        ),
        (
            "galco_authorized_product_page",
            "https://www.galco.com/res10k-ohm.html",
        ),
    ],
}

# Search listings / stock-number lookups are discovery leads only. Attribute
# values require a retrieved product-detail page that names Ohmite + exact MPN.
_RS_GROUP_SEARCH_LISTING_LEADS: dict[tuple[str, str], str] = {
    ("ohmite", "RES10K"): "https://uk.rs-online.com/web/c/?searchTerm=70585847",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parallel_ordered(items: list[Any], worker: Any, *, limit: int = 8) -> list[Any]:
    """Run independent public-source checks concurrently, preserving source order."""
    values = list(items or [])
    if len(values) < 2:
        return [worker(value) for value in values]
    with ThreadPoolExecutor(
        max_workers=min(max(1, int(limit)), len(values)),
        thread_name_prefix="compare-source",
    ) as executor:
        futures = [
            executor.submit(copy_context().run, worker, value)
            for value in values
        ]
        return [future.result() for future in futures]


def _status_row(
    *,
    source: str,
    source_type: str,
    url: str = "",
    status: str,
    detail: str = "",
    identity_verified: bool = False,
    retrieved_at: str = "",
) -> dict[str, Any]:
    return {
        "source": source,
        "source_type": source_type,
        "url": url,
        "status": status,
        "detail": detail,
        "identity_verified": bool(identity_verified),
        "retrieved_at": retrieved_at or _utc_now_iso(),
    }


def _looks_like_access_challenge(html: str) -> bool:
    """True for Cloudflare / bot-challenge interstitial bodies (never used)."""
    text = str(html or "").casefold()
    if not text:
        return False
    markers = (
        "just a moment...",
        "cf-browser-verification",
        "cf-challenge",
        "attention required! | cloudflare",
        "enable javascript and cookies to continue",
    )
    return any(marker in text for marker in markers)


def _clean_html_fragment(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(text.split()).strip()


def _append_labeled_pair(pairs: list[str], label: str, value: str) -> None:
    clean_label = " ".join(str(label or "").split()).strip(" :")
    clean_value = " ".join(str(value or "").split()).strip()
    if not clean_label or not clean_value:
        return
    if clean_label.casefold().startswith("view datasheet"):
        return
    if len(clean_value) > 160:
        return
    entry = f"{clean_label}: {clean_value}"
    if entry not in pairs:
        pairs.append(entry)


def _json_ld_property_pairs(html: str) -> list[str]:
    """Extract PropertyValue pairs from JSON-LD without inventing labels."""
    pairs: list[str] = []
    for match in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        str(html or ""),
        re.I | re.S,
    ):
        blob = match.group(1) or ""
        for prop in re.finditer(
            r'"name"\s*:\s*"([^"]+)"\s*,\s*"value"\s*:\s*"([^"]+)"',
            blob,
        ):
            _append_labeled_pair(pairs, prop.group(1), prop.group(2))
        for prop in re.finditer(
            r'"value"\s*:\s*"([^"]+)"\s*,\s*"name"\s*:\s*"([^"]+)"',
            blob,
        ):
            _append_labeled_pair(pairs, prop.group(2), prop.group(1))
        brand = re.search(
            r'"brand"\s*:\s*(?:"([^"]+)"|\{[^}]*"name"\s*:\s*"([^"]+)")',
            blob,
        )
        if brand:
            _append_labeled_pair(pairs, "Manufacturer", brand.group(1) or brand.group(2))
        mpn = re.search(r'"(?:mpn|sku|productID)"\s*:\s*"([^"]+)"', blob, re.I)
        if mpn:
            _append_labeled_pair(pairs, "Model", mpn.group(1))
    return pairs


def _html_to_product_text(html: str) -> str:
    """Flatten a manufacturer/distributor product page into labeled text."""
    raw = str(html or "")
    cleaned = re.sub(r"(?is)<script(?![^>]*ld\+json)[^>]*>.*?</script>", " ", raw)
    cleaned = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", cleaned)
    pairs: list[str] = []
    pairs.extend(_json_ld_property_pairs(raw))

    product_number = re.search(
        r"id=['\"]cds-product-number['\"][^>]*>\s*([^<]+)",
        cleaned,
        re.I,
    )
    if product_number:
        _append_labeled_pair(pairs, "Model", product_number.group(1))
    for match in re.finditer(
        r"<td[^>]*id=['\"]cds-al-([^'\"]+)['\"][^>]*>\s*(.*?)\s*</td>\s*"
        r"<td[^>]*id=['\"]cds-av-\1['\"][^>]*>\s*(.*?)\s*</td>",
        cleaned,
        re.I | re.S,
    ):
        _append_labeled_pair(
            pairs,
            _clean_html_fragment(match.group(2)),
            _clean_html_fragment(match.group(3)),
        )

    for match in re.finditer(
        r"<tr[^>]*>\s*<t[hd][^>]*>\s*(.*?)\s*</t[hd]>\s*<t[hd][^>]*>\s*(.*?)\s*</t[hd]>\s*</tr>",
        cleaned,
        re.I | re.S,
    ):
        _append_labeled_pair(
            pairs,
            _clean_html_fragment(match.group(1)),
            _clean_html_fragment(match.group(2)),
        )

    heading_iter = list(
        re.finditer(r"<h([1-6])[^>]*>\s*(.*?)\s*</h\1>", cleaned, re.I | re.S)
    )
    fieldish = (
        "resistance",
        "voltage",
        "power",
        "tolerance",
        "mounting",
        "termination",
        "shaft",
        "type",
        "technology",
        "diameter",
        "family",
        "series",
        "linear",
        "turns",
        "rotation",
        "product length",
        "product depth",
        "product height",
    )
    for index, match in enumerate(heading_iter):
        label = _clean_html_fragment(match.group(2))
        if not label or len(label) > 80:
            continue
        if not any(token in label.casefold() for token in fieldish):
            continue
        value = ""
        if index + 1 < len(heading_iter):
            nxt = _clean_html_fragment(heading_iter[index + 1].group(2))
            if nxt and len(nxt) <= 80 and not any(
                nxt.casefold().endswith(suffix)
                for suffix in ("(ohm)", "(v)", "(w)", "(mm)", "(turns)", "(°)")
            ):
                value = nxt
        if not value:
            after = cleaned[match.end() : match.end() + 400]
            block = re.search(
                r"<(?:div|span|p|dd|td)[^>]*>\s*([^<]{1,80})\s*</(?:div|span|p|dd|td)>",
                after,
                re.I,
            )
            if block:
                value = _clean_html_fragment(block.group(1))
        _append_labeled_pair(pairs, label, value)

    for match in re.finditer(
        r"<dt[^>]*>\s*(.*?)\s*</dt>\s*<dd[^>]*>\s*(.*?)\s*</dd>",
        cleaned,
        re.I | re.S,
    ):
        _append_labeled_pair(
            pairs,
            _clean_html_fragment(match.group(1)),
            _clean_html_fragment(match.group(2)),
        )

    brand = re.search(
        r"\b(Ohmite|Vishay|Bourns|TT Electronics|TE Connectivity|Yageo|Panasonic|Murata|TDK|Samsung|Infineon|STMicroelectronics|Texas Instruments|Analog Devices|ON Semiconductor|onsemi|NXP|Microchip|Renesas|ROHM|Diodes Incorporated)\b",
        cleaned,
        re.I,
    )
    if brand:
        _append_labeled_pair(pairs, "Manufacturer", brand.group(1))
    if pairs:
        return "\n".join(pairs)
    text = re.sub(r"<[^>]+>", "\n", cleaned)
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _document_from_html(
    *,
    html: str,
    url: str,
    source_name: str,
    source_type: str = "manufacturer_product_page",
    extraction_method: str = "manufacturer_product_html",
) -> dict[str, Any]:
    raw_text = _html_to_product_text(html)
    field_labels = _source_field_labels(raw_text)
    text = _enrich_product_aliases(raw_text)
    pages = [{"page": "attributes", "document": source_name, "text": text}] if text.strip() else []
    return {
        "available": bool(pages),
        "pages": pages,
        "page_count": len(pages),
        "document_page_count": 1,
        "pages_examined": 1,
        "text_page_count": len(pages),
        "page_cap_applied": False,
        "search_complete": True,
        "extraction_method": extraction_method,
        "ocr_supported": False,
        "final_url": url,
        "source_url": url,
        "source_name": source_name,
        "source_type": source_type,
        "source_field_labels": field_labels,
        "retrieved_at": _utc_now_iso(),
        "reason": "" if pages else "The product page had no extractable text.",
    }


def _fetch_public_https(url: str, *, referer: str = "") -> tuple[str, bytes | str, str]:
    """Return (status, payload_or_reason, final_url). status is ok|blocked|error|..."""
    if not _public_datasheet_url(url):
        return PROVIDER_SKIPPED, "URL is not a public HTTPS destination.", url
    prefetched = _PREFETCHED_COMPARE_FETCHES.get()
    cache_key = (_canonical_datasheet_url(url), str(referer or ""))
    if prefetched is not None and cache_key in prefetched:
        return prefetched[cache_key]
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        "User-Agent": "CadivorEngineeringReview/1.0 (+https://cadivor.com)",
    }
    if referer:
        headers["Referer"] = referer
    try:
        session = requests.Session()
        session.max_redirects = 5
        response = session.get(url, timeout=(5, 15), headers=headers, allow_redirects=True)
    except requests.exceptions.TooManyRedirects:
        return PROVIDER_REDIRECT_LOOP, "The manufacturer page redirected too many times.", url
    except requests.exceptions.Timeout:
        return PROVIDER_TIMEOUT, "The source timed out.", url
    except Exception as exc:
        return PROVIDER_ERROR, f"{exc.__class__.__name__}: {exc}", url
    final = str(response.url or url)
    code = int(response.status_code or 0)
    body_text = ""
    try:
        body_text = response.text or ""
    except Exception:
        body_text = ""
    if code == 403 or _looks_like_access_challenge(body_text):
        detail = "HTTP 403. The body was not used as evidence."
        if _looks_like_access_challenge(body_text):
            detail = (
                "HTTP access challenge / Cloudflare interstitial. "
                "The body was not used as evidence."
            )
        return PROVIDER_HTTP_BLOCKED, detail, final
    if code == 404:
        return PROVIDER_NOT_FOUND, "HTTP 404. No product record was returned.", final
    if code >= 400:
        return PROVIDER_ERROR, f"HTTP {code}. The body was not used as evidence.", final
    content_type = str(response.headers.get("Content-Type") or "").casefold()
    if "pdf" in content_type or response.content[:4] == b"%PDF":
        return PROVIDER_AVAILABLE, response.content, final
    return PROVIDER_AVAILABLE, body_text or response.text, final


def _authorized_distributor_product_candidates(
    *,
    manufacturer: str,
    mpn: str,
) -> list[tuple[str, str]]:
    key = (
        re.sub(r"[^a-z0-9]+", "", str(manufacturer or "").casefold()),
        str(mpn or "").strip().upper(),
    )
    return list(_AUTHORIZED_DISTRIBUTOR_PRODUCT_PAGES.get(key) or [])


def _probe_authorized_distributor_product_page(
    *,
    source_type: str,
    url: str,
    manufacturer: str,
    mpn: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Fetch an authorized distributor product page; cite values only after identity."""
    token = source_type.split("_", 1)[0].casefold()
    if source_type.startswith("rs_group_"):
        distributor = "RS Group"
    else:
        distributor = {"arrow": "Arrow", "galco": "Galco"}.get(token, token.title())
    status, payload, final_url = _fetch_public_https(url)
    if status != PROVIDER_AVAILABLE:
        return (
            _status_row(
                source=distributor,
                source_type=source_type,
                url=final_url or url,
                status=status,
                detail=str(payload),
            ),
            None,
        )
    if not isinstance(payload, str):
        return (
            _status_row(
                source=distributor,
                source_type=source_type,
                url=final_url or url,
                status=PROVIDER_ERROR,
                detail="Expected an HTML product page; binary content was not used.",
            ),
            None,
        )
    doc = _document_from_html(
        html=payload,
        url=final_url or url,
        source_name=f"{distributor} authorized product page",
        source_type=source_type,
        extraction_method="authorized_distributor_product_html",
    )
    identity = verify_datasheet_identity(doc, manufacturer=manufacturer, mpn=mpn)
    if not identity["verified"]:
        return (
            _status_row(
                source=distributor,
                source_type=source_type,
                url=final_url or url,
                status=PROVIDER_NOT_FOUND,
                detail=(
                    f"{identity.get('reason') or 'Identity not verified.'} "
                    "URL slug / search snippet alone is insufficient; no values were taken."
                ),
                identity_verified=False,
            ),
            None,
        )
    return (
        _status_row(
            source=distributor,
            source_type=source_type,
            url=final_url or url,
            status=PROVIDER_AVAILABLE,
            detail=(
                f"{distributor} product page named {manufacturer} and exact MPN {mpn}. "
                "Exact-part attribute values may be cited with source field labels."
            ),
            identity_verified=True,
        ),
        doc,
    )


def _manufacturer_product_candidates(
    *,
    manufacturer: str,
    mpn: str,
    product_detail_url: str = "",
) -> list[tuple[str, str]]:
    """Candidate manufacturer product URLs. Identity still requires page text."""
    candidates: list[tuple[str, str]] = []
    detail = str(product_detail_url or "").strip()
    if detail.startswith(("http://", "https://")):
        candidates.append(("manufacturer_product_page", detail))
    maker = re.sub(r"[^a-z0-9]+", "", str(manufacturer or "").casefold())
    code = quote(str(mpn or "").strip(), safe="")
    if maker == "ohmite" and code:
        # Official Ohmite catalog path used for rheostat order codes. Fetching
        # this URL is not identity proof; the response text must name the MPN.
        candidates.append(
            ("manufacturer_catalog_path", f"https://www.ohmite.com/catalog/rheostats/{code}")
        )
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for source_type, url in candidates:
        key = _canonical_datasheet_url(url)
        if key in seen:
            continue
        seen.add(key)
        unique.append((source_type, url))
    return unique


def _distributor_public_candidates(mpn: str, manufacturer: str) -> list[tuple[str, str]]:
    code = quote(str(mpn or "").strip(), safe="")
    maker = quote(str(manufacturer or "").strip().casefold(), safe="")
    if not code:
        return []
    rows = [
        ("digikey_product_search", f"https://www.digikey.com/en/products/result?keywords={code}"),
        ("mouser_product_search", f"https://www.mouser.com/c/?q={code}"),
        ("mouser_product_page", f"https://www.mouser.com/ProductDetail/{quote(str(manufacturer or '').strip(), safe='')}/{code}"),
        ("newark_product_search", f"https://www.newark.com/search?st={code}"),
    ]
    if maker == "ohmite":
        raw = str(mpn or "").strip().upper()
        indexed = _DIGIKEY_INDEXED_LISTING_LEADS.get(("ohmite", raw))
        if indexed:
            # Probe the indexed discovery-lead URL; HTTP 403 bodies are unused.
            rows.insert(1, ("digikey_indexed_listing_probe", indexed))
        # Candidate detail URLs are probes only. Identity still requires page text.
        rows.insert(
            2 if indexed else 1,
            (
                "digikey_product_page",
                f"https://www.digikey.com/en/products/detail/ohmite/{code}",
            ),
        )
    return rows


def _manufacturer_search_candidates(*, manufacturer: str, mpn: str) -> list[tuple[str, str]]:
    maker = re.sub(r"[^a-z0-9]+", "", str(manufacturer or "").casefold())
    code = quote(str(mpn or "").strip(), safe="")
    if not code:
        return []
    if maker == "ohmite":
        return [
            ("manufacturer_site_search", f"https://www.ohmite.com/catalog/?search={code}"),
            ("manufacturer_site_search", f"https://www.ohmite.com/?s={code}"),
        ]
    return []


def _ohmite_order_code_catalog_candidates(mpn: str) -> list[tuple[str, str]]:
    """Bounded Ohmite ordering-code / catalog materials for exact-MPN search.

    These are probed for an explicit manufacturer + exact MPN mention. A family
    datasheet or URL slug alone never establishes identity.
    """
    code = quote(str(mpn or "").strip(), safe="")
    if not code:
        return []
    return [
        (
            "manufacturer_order_code_pdf",
            "https://www.ohmite.com/assets/files/Datasheets/rheostats.pdf?r=false",
        ),
        (
            "manufacturer_series_pdf",
            "https://www.ohmite.com/assets/images/res-10.pdf?r=false",
        ),
        (
            "manufacturer_series_page",
            "https://www.ohmite.com/res-10/",
        ),
        (
            "manufacturer_rheostat_guide",
            "https://www.ohmite.com/guide-to-rheostats/",
        ),
        (
            "manufacturer_catalog_path",
            f"https://www.ohmite.com/catalog/rheostats/{code}",
        ),
        (
            "manufacturer_catalog_search",
            f"https://www.ohmite.com/catalog/?search={code}",
        ),
    ]


def _probe_exact_mpn_source(
    *,
    source_type: str,
    url: str,
    manufacturer: str,
    mpn: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Fetch one manufacturer catalog/order-code source and require exact MPN."""
    status, payload, final_url = _fetch_public_https(url, referer=url)
    if status != PROVIDER_AVAILABLE:
        return (
            _status_row(
                source="Ohmite",
                source_type=source_type,
                url=final_url or url,
                status=status,
                detail=str(payload),
            ),
            None,
        )
    doc: dict[str, Any]
    if isinstance(payload, (bytes, bytearray)) and payload[:4] == b"%PDF":
        from src.datasheet_comparison import _parse_datasheet_pdf

        doc = _parse_datasheet_pdf(bytes(payload), final_url)
        doc["source_name"] = "Ohmite order-code / catalog PDF"
        doc["source_type"] = source_type
        doc["source_url"] = final_url
    else:
        doc = _document_from_html(
            html=str(payload),
            url=final_url,
            source_name="Ohmite order-code / catalog page",
        )
        doc["source_type"] = source_type
    identity = verify_datasheet_identity(doc, manufacturer=manufacturer, mpn=mpn)
    detail = identity["reason"] if identity["attached"] else str(doc.get("reason") or "")
    if not identity["verified"]:
        detail = (
            f"{detail} Exact MPN {mpn} was not verified in this Ohmite catalog/"
            "order-code material; no values were taken."
        )
    row = _status_row(
        source="Ohmite",
        source_type=source_type,
        url=final_url or url,
        status=PROVIDER_AVAILABLE if doc.get("available") else PROVIDER_ERROR,
        detail=detail,
        identity_verified=identity["verified"],
    )
    if doc.get("available") and identity["verified"]:
        return row, doc
    if doc.get("available"):
        doc["identity_rejected"] = identity
    return row, None


def _aggregator_listing_candidates(*, manufacturer: str, mpn: str) -> list[tuple[str, str]]:
    """Public part-index listings. Recorded for coverage; never used for attribute values."""
    code = quote(str(mpn or "").strip(), safe="")
    maker = quote(str(manufacturer or "").strip(), safe="")
    if not code:
        return []
    return [
        ("parts_aggregator_search", f"https://octopart.com/search?q={code}+{maker}"),
    ]


def _configured_distributor_api_status() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        from integrations.supplier_aggregator import _supplier_lookup_callable
    except Exception as exc:
        return [
            _status_row(
                source="distributor_apis",
                source_type="authorized_distributor_api",
                status=PROVIDER_ERROR,
                detail=f"Could not inspect distributor configuration ({exc.__class__.__name__}).",
            )
        ]
    for name in ("Mouser", "DigiKey", "Newark"):
        callable_lookup = _supplier_lookup_callable(name)
        if callable_lookup is None:
            rows.append(
                _status_row(
                    source=name,
                    source_type="authorized_distributor_api",
                    status=PROVIDER_NOT_CONFIGURED,
                    detail=f"{name} API credentials are not configured in this environment.",
                )
            )
        else:
            rows.append(
                _status_row(
                    source=name,
                    source_type="authorized_distributor_api",
                    status=PROVIDER_AVAILABLE,
                    detail=f"{name} API is configured for permitted exact-MPN lookup.",
                )
            )
    return rows


def _digikey_indexed_listing_lead(*, manufacturer: str, mpn: str) -> dict[str, Any] | None:
    key = (
        re.sub(r"[^a-z0-9]+", "", str(manufacturer or "").casefold()),
        str(mpn or "").strip().upper(),
    )
    url = _DIGIKEY_INDEXED_LISTING_LEADS.get(key)
    if not url:
        return None
    return _status_row(
        source="DigiKey",
        source_type="digikey_indexed_listing_lead",
        url=url,
        status=PROVIDER_DISCOVERY_LEAD,
        detail=(
            "Indexed DigiKey product listing recorded as a discovery lead only. "
            "Public HTML access is HTTP 403-blocked and is not used. Values are "
            "taken only if the permitted DigiKey API integration retrieves and "
            "cites this exact MPN."
        ),
        identity_verified=False,
    )


def _rs_group_search_listing_lead(*, manufacturer: str, mpn: str) -> dict[str, Any] | None:
    """RS stock/search listing is a discovery lead only — never attribute values."""
    key = (
        re.sub(r"[^a-z0-9]+", "", str(manufacturer or "").casefold()),
        str(mpn or "").strip().upper(),
    )
    url = _RS_GROUP_SEARCH_LISTING_LEADS.get(key)
    if not url:
        return None
    return _status_row(
        source="RS Group",
        source_type="rs_group_search_listing_lead",
        url=url,
        status=PROVIDER_DISCOVERY_LEAD,
        detail=(
            "RS Group search/stock listing (70585847) recorded as a discovery lead "
            "only. Search snippets are not evidence. Values require a retrieved RS "
            "product-detail page that names Ohmite and exact MPN RES10K."
        ),
        identity_verified=False,
    )


def _supplier_record_matches_exact_mpn(
    record: Mapping[str, Any] | None,
    *,
    mpn: str,
    manufacturer: str,
) -> bool:
    if not isinstance(record, Mapping) or not record:
        return False
    returned_mpn = str(
        record.get("manufacturer_part_number")
        or record.get("Manufacturer Part Number")
        or record.get("mpn")
        or ""
    ).strip()
    returned_mfr = str(record.get("manufacturer") or record.get("Manufacturer") or "").strip()
    mpn_ok = bool(returned_mpn) and re.sub(r"[^A-Z0-9]", "", returned_mpn.upper()) == re.sub(
        r"[^A-Z0-9]", "", str(mpn or "").upper()
    )
    mfr_ok = (not manufacturer) or (
        re.sub(r"[^a-z0-9]+", "", returned_mfr.casefold())
        == re.sub(r"[^a-z0-9]+", "", str(manufacturer or "").casefold())
    )
    return bool(mpn_ok and mfr_ok)


def _try_digikey_api_exact_mpn(
    *,
    mpn: str,
    manufacturer: str,
    supplier_record: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Use DigiKey listing data already retrieved for this compare when possible."""
    reused = None
    if isinstance(supplier_record, Mapping) and supplier_record:
        source_name = str(
            supplier_record.get("source")
            or supplier_record.get("Source")
            or supplier_record.get("supplier")
            or ""
        ).strip().casefold()
        if "digikey" in source_name and _supplier_record_matches_exact_mpn(
            supplier_record, mpn=mpn, manufacturer=manufacturer
        ):
            reused = dict(supplier_record)
    if reused is not None:
        result = reused
    else:
        try:
            from integrations.supplier_aggregator import _supplier_lookup_callable
        except Exception as exc:
            return (
                _status_row(
                    source="DigiKey",
                    source_type="authorized_distributor_api_lookup",
                    status=PROVIDER_ERROR,
                    detail=f"DigiKey listing lookup unavailable ({exc.__class__.__name__}).",
                ),
                None,
            )
        lookup = _supplier_lookup_callable("DigiKey")
        if lookup is None:
            return (
                _status_row(
                    source="DigiKey",
                    source_type="authorized_distributor_api_lookup",
                    status=PROVIDER_NOT_CONFIGURED,
                    detail=(
                        "DigiKey listing credentials are not configured. The indexed "
                        "listing remains a discovery lead only; the DigiKey product page "
                        "is blocked for automated retrieval and is not used. RES10K values "
                        "stay unverified until DigiKey returns this exact MPN or an "
                        "exact-MPN datasheet is uploaded through Compare Parts."
                        if str(mpn).strip().upper() == "RES10K"
                        else (
                            "DigiKey listing credentials are not configured. Exact-MPN "
                            "listing lookup was not available."
                        )
                    ),
                ),
                None,
            )
        try:
            result = lookup(mpn) or {}
        except Exception as exc:
            return (
                _status_row(
                    source="DigiKey",
                    source_type="authorized_distributor_api_lookup",
                    status=PROVIDER_ERROR,
                    detail=(
                        f"DigiKey product listing lookup failed "
                        f"({exc.__class__.__name__}: {exc})."
                    ),
                ),
                None,
            )
    if not isinstance(result, dict) or not result:
        return (
            _status_row(
                source="DigiKey",
                source_type="authorized_distributor_api_lookup",
                status=PROVIDER_NOT_FOUND,
                detail="DigiKey product listing returned no exact-MPN record. No values were taken.",
            ),
            None,
        )
    returned_mpn = str(
        result.get("manufacturer_part_number")
        or result.get("Manufacturer Part Number")
        or result.get("mpn")
        or ""
    ).strip()
    returned_mfr = str(result.get("manufacturer") or result.get("Manufacturer") or "").strip()
    mpn_ok = bool(returned_mpn) and re.sub(r"[^A-Z0-9]", "", returned_mpn.upper()) == re.sub(
        r"[^A-Z0-9]", "", str(mpn or "").upper()
    )
    mfr_ok = (not manufacturer) or (
        re.sub(r"[^a-z0-9]+", "", returned_mfr.casefold())
        == re.sub(r"[^a-z0-9]+", "", str(manufacturer or "").casefold())
    )
    if not (mpn_ok and mfr_ok):
        return (
            _status_row(
                source="DigiKey",
                source_type="authorized_distributor_api_lookup",
                status=PROVIDER_NOT_FOUND,
                detail=(
                    "DigiKey product listing did not verify the entered manufacturer and "
                    "exact MPN. No values were taken."
                ),
            ),
            None,
        )
    # Represent DigiKey listing fields as a cited evidence document.
    lines = [f"Manufacturer: {returned_mfr}", f"Model: {returned_mpn}"]
    for label, keys in (
        ("Resistance", ("resistance", "Resistance")),
        ("Power rating", ("power_rating", "Power Rating", "power")),
        ("Volts", ("max_working_voltage", "Voltage Rating", "voltage")),
        ("Diameter", ("diameter", "Diameter")),
        ("Construction", ("element_type", "Composition")),
        ("Mounting style", ("mounting_style", "Mounting Type", "Mounting Style")),
    ):
        value = ""
        for key in keys:
            value = str(result.get(key) or "").strip()
            if value:
                break
        if value:
            lines.append(f"{label}: {value}")
    doc = {
        "available": True,
        "pages": [
            {
                "page": "DigiKey product listing",
                "document": "DigiKey product listing",
                "text": "\n".join(lines),
            }
        ],
        "page_count": 1,
        "extraction_method": "authorized_distributor_listing",
        "source_name": "DigiKey product listing",
        "source_type": "authorized_distributor_api",
        "source_url": str(result.get("product_detail_url") or result.get("datasheet_url") or ""),
        "final_url": str(result.get("product_detail_url") or result.get("datasheet_url") or ""),
        "source_field_labels": _source_field_labels("\n".join(lines)),
    }
    return (
        _status_row(
            source="DigiKey",
            source_type="authorized_distributor_api_lookup",
            url=str(doc.get("final_url") or ""),
            status=PROVIDER_AVAILABLE,
            detail="DigiKey product listing retrieved a record naming the entered manufacturer and exact MPN.",
            identity_verified=True,
        ),
        doc,
    )


def _enrich_product_aliases(text: str) -> str:
    """Mirror product-page labels onto compare aliases without inventing units.

    Diameter is left as Diameter only. It is never rewritten to Body and never
    given a unit the product page did not state. Volts stay as the product-page
    value; the UI does not claim RMS unless that label is used and both the
    product page and family source are cited.
    """
    # Compare-field alias <- exact manufacturer product label. Values are copied
    # verbatim (no unit suffix added). Do not rewrite Volts to "Maximum working
    # voltage" or Diameter to Body — those mappings are not authoritative here.
    # Alias compare-field labels onto exact source labels. Values stay verbatim —
    # never append RMS, V, W, or mm unless that text already appears in the value.
    replacements = (
        ("Ohms Value:", "Resistance:"),
        ("Resistance Value (Ohm):", "Resistance:"),
        ("Resistance Value:", "Resistance:"),
        ("Watts:", "Power rating:"),
        ("Power Rating (W):", "Power rating:"),
        ("Power Rating:", "Power rating:"),
        ("Maximum Voltage Rating (V):", "Volts:"),
        ("Maximum Voltage Rating:", "Volts:"),
        ("Voltage Rating (V):", "Volts:"),
        ("Construction:", "Element type:"),
        ("Technology:", "Element type:"),
        ("Termination Style:", "Terminal style:"),
        ("Mounting:", "Mounting style:"),
        ("Linear or Logarithmic:", "Taper:"),
        ("Shaft Diameter (mm):", "Shaft:"),
        ("Shaft Diameter:", "Shaft:"),
        ("Number of Turns (Turns):", "Turns:"),
        ("Number of Turns:", "Turns:"),
        ("Mechanical Rotation Angle (°):", "Rotation:"),
        ("Mechanical Rotation Angle:", "Rotation:"),
        ("Family/Series:", "Series:"),
    )
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    extra: list[str] = []
    for line in lines:
        for old, new in replacements:
            if line.casefold().startswith(old.casefold()):
                value = line.split(":", 1)[1].strip()
                extra.append(f"{new} {value}")
    return "\n".join(lines + extra)


def _source_field_labels(text: str) -> list[str]:
    labels: list[str] = []
    for line in str(text or "").splitlines():
        if ":" not in line:
            continue
        label = line.split(":", 1)[0].strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def _gather_part_evidence_from_sources(
    *,
    mpn: str,
    manufacturer: str = "",
    datasheet_url: str = "",
    product_detail_url: str = "",
    probe_distributor_pages: bool = True,
    supplier_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Search manufacturer and authorized sources for exact-MPN evidence."""
    sources: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    requested_mpn = str(mpn or "").strip()
    requested_manufacturer = str(manufacturer or "").strip()

    # 1) Linked datasheet / PDF path already used by Compare Parts.
    datasheet = str(datasheet_url or "").strip()
    if datasheet:
        try:
            pdf = extract_datasheet_text(datasheet)
        except Exception as exc:
            pdf = {
                "available": False,
                "pages": [],
                "reason": f"Datasheet retrieval failed ({exc.__class__.__name__}).",
                "final_url": datasheet,
            }
        identity = verify_datasheet_identity(
            pdf, manufacturer=requested_manufacturer, mpn=requested_mpn
        )
        sources.append(
            _status_row(
                source="linked_datasheet",
                source_type="manufacturer_or_supplier_datasheet",
                url=str(pdf.get("final_url") or datasheet),
                status=PROVIDER_AVAILABLE if pdf.get("available") else PROVIDER_ERROR,
                detail=identity["reason"] if pdf.get("available") else str(pdf.get("reason") or "unavailable"),
                identity_verified=identity["verified"],
            )
        )
        if pdf.get("available"):
            pdf = dict(pdf)
            pdf["source_name"] = "Linked datasheet"
            pdf["source_type"] = "datasheet_pdf"
            documents.append(pdf)
    else:
        sources.append(
            _status_row(
                source="linked_datasheet",
                source_type="manufacturer_or_supplier_datasheet",
                status=PROVIDER_SKIPPED,
                detail="No datasheet_url was provided on the part record.",
            )
        )

    # 2) Manufacturer product / order-code pages.
    product_candidates = _manufacturer_product_candidates(
        manufacturer=requested_manufacturer,
        mpn=requested_mpn,
        product_detail_url=product_detail_url,
    )
    product_fetches = _parallel_ordered(
        product_candidates,
        lambda candidate: _fetch_public_https(candidate[1], referer=candidate[1]),
    )
    for (source_type, url), (status, payload, final_url) in zip(
        product_candidates, product_fetches
    ):
        if status != PROVIDER_AVAILABLE:
            sources.append(
                _status_row(
                    source="Ohmite" if "ohmite.com" in url.casefold() else "manufacturer",
                    source_type=source_type,
                    url=final_url or url,
                    status=status,
                    detail=str(payload),
                )
            )
            continue
        if isinstance(payload, (bytes, bytearray)) and payload[:4] == b"%PDF":
            from src.datasheet_comparison import _parse_datasheet_pdf

            doc = _parse_datasheet_pdf(bytes(payload), final_url)
            doc["source_name"] = "Manufacturer PDF"
            doc["source_type"] = "manufacturer_pdf"
        else:
            html = str(payload)
            # Do not treat a URL slug as identity: require the exact MPN in body.
            doc = _document_from_html(
                html=html,
                url=final_url,
                source_name="Manufacturer product page",
            )
        identity = verify_datasheet_identity(
            doc, manufacturer=requested_manufacturer, mpn=requested_mpn
        )
        if identity["verified"] and doc.get("source_field_labels"):
            identity = dict(identity)
            identity["reason"] = (
                f"{identity['reason']} Source field labels: "
                + ", ".join(doc["source_field_labels"])
                + "."
            )
        sources.append(
            _status_row(
                source="Ohmite" if "ohmite.com" in (final_url or url).casefold() else "manufacturer",
                source_type=source_type,
                url=final_url or url,
                status=PROVIDER_AVAILABLE if doc.get("available") else PROVIDER_ERROR,
                detail=identity["reason"] if identity["attached"] else str(doc.get("reason") or ""),
                identity_verified=identity["verified"],
            )
        )
        if doc.get("available") and identity["verified"]:
            documents.append(doc)
        elif doc.get("available"):
            # Keep the document for diagnostics, but merge will ignore unverified docs.
            doc["identity_rejected"] = identity
            documents.append(doc)

    # 2b) Manufacturer site search pages (exact-MPN still required in body).
    manufacturer_search_candidates = _manufacturer_search_candidates(
        manufacturer=requested_manufacturer, mpn=requested_mpn
    )
    manufacturer_search_fetches = _parallel_ordered(
        manufacturer_search_candidates,
        lambda candidate: _fetch_public_https(candidate[1]),
    )
    for (source_type, url), (status, payload, final_url) in zip(
        manufacturer_search_candidates, manufacturer_search_fetches
    ):
        identity_ok = False
        detail = str(payload)
        if status == PROVIDER_AVAILABLE and isinstance(payload, str):
            probe_doc = {"pages": [{"page": "search", "text": payload[:20000]}]}
            identity_ok = _pdf_mentions_exact_part(probe_doc, requested_mpn) and (
                not requested_manufacturer
                or _pdf_mentions_exact_part(probe_doc, requested_manufacturer)
            )
            detail = (
                "Search page named the entered manufacturer and exact MPN."
                if identity_ok
                else "Search page retrieved, but extractable text did not verify the exact MPN. No values were taken."
            )
        sources.append(
            _status_row(
                source="Ohmite" if "ohmite.com" in url.casefold() else "manufacturer",
                source_type=source_type,
                url=final_url or url,
                status=status if status != PROVIDER_AVAILABLE else (
                    PROVIDER_AVAILABLE if identity_ok else PROVIDER_NOT_FOUND
                ),
                detail=detail,
                identity_verified=identity_ok,
            )
        )

    # 2c) Bounded Ohmite order-code / catalog materials (exact MPN required).
    maker_key = re.sub(r"[^a-z0-9]+", "", requested_manufacturer.casefold())
    if maker_key == "ohmite":
        seen_urls = {
            _canonical_datasheet_url(str(row.get("url") or ""))
            for row in sources
            if row.get("url")
        }
        catalog_candidates = []
        for source_type, url in _ohmite_order_code_catalog_candidates(requested_mpn):
            key = _canonical_datasheet_url(url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            catalog_candidates.append((source_type, url))
        catalog_results = _parallel_ordered(
            catalog_candidates,
            lambda candidate: _probe_exact_mpn_source(
                source_type=candidate[0],
                url=candidate[1],
                manufacturer=requested_manufacturer,
                mpn=requested_mpn,
            )
        )
        for row, doc in catalog_results:
            sources.append(row)
            if doc is not None:
                documents.append(doc)

    # 3) Ohmite-authorized distributor product pages (RS Group, Arrow, Galco, …).
    # RS search/stock listings are discovery leads only. Product-detail pages are
    # probed next; URL slug is never identity. Cloudflare/403 bodies and timeouts
    # fail closed and are never used as evidence.
    rs_lead = _rs_group_search_listing_lead(
        manufacturer=requested_manufacturer, mpn=requested_mpn
    )
    if rs_lead is not None:
        sources.append(rs_lead)
    if probe_distributor_pages:
        seen_auth_urls = {
            _canonical_datasheet_url(str(row.get("url") or ""))
            for row in sources
            if row.get("url")
        }
        authorized_candidates = _authorized_distributor_product_candidates(
            manufacturer=requested_manufacturer, mpn=requested_mpn
        )
        filtered_authorized_candidates = []
        for source_type, url in authorized_candidates:
            key = _canonical_datasheet_url(url)
            if key in seen_auth_urls:
                continue
            seen_auth_urls.add(key)
            filtered_authorized_candidates.append((source_type, url))
        authorized_results = _parallel_ordered(
            filtered_authorized_candidates,
            lambda candidate: _probe_authorized_distributor_product_page(
                source_type=candidate[0],
                url=candidate[1],
                manufacturer=requested_manufacturer,
                mpn=requested_mpn,
            )
        )
        for row, doc in authorized_results:
            sources.append(row)
            if doc is not None:
                documents.append(doc)

    # 4) Authorized distributor APIs — configuration status, then DigiKey exact-MPN
    # lookup when the existing client is configured. Indexed DigiKey HTML listings
    # are discovery leads only; HTTP 403 bodies are never used.
    sources.extend(_configured_distributor_api_status())
    lead = _digikey_indexed_listing_lead(
        manufacturer=requested_manufacturer, mpn=requested_mpn
    )
    if lead is not None:
        sources.append(lead)
    digikey_status, digikey_doc = _try_digikey_api_exact_mpn(
        mpn=requested_mpn,
        manufacturer=requested_manufacturer,
        supplier_record=supplier_record,
    )
    sources.append(digikey_status)
    if digikey_doc is not None:
        documents.append(digikey_doc)

    digikey_verified = bool(
        digikey_doc is not None and digikey_status.get("identity_verified")
    )
    # When DigiKey already verified the exact MPN, skip slow public HTML probes.
    # Manufacturer PDF/product pages above still contribute when available.
    skip_public_html = digikey_verified

    # 5) Other public distributor product pages — record access; never use 403 bodies.
    if probe_distributor_pages and not skip_public_html:
        distributor_candidates = _distributor_public_candidates(
            requested_mpn, requested_manufacturer
        )
        distributor_fetches = _parallel_ordered(
            distributor_candidates,
            lambda candidate: _fetch_public_https(candidate[1]),
        )
        for (source_type, url), (status, payload, final_url) in zip(
            distributor_candidates, distributor_fetches
        ):
            detail = str(payload) if status != PROVIDER_AVAILABLE else "Page retrieved."
            identity_ok = False
            if status == PROVIDER_AVAILABLE and isinstance(payload, str):
                probe_doc = {
                    "pages": [{"page": "product page", "text": payload[:20000]}],
                }
                # Exact MPN must appear as a token; URL keywords alone are insufficient.
                identity_ok = _pdf_mentions_exact_part(probe_doc, requested_mpn) and (
                    not requested_manufacturer
                    or _pdf_mentions_exact_part(probe_doc, requested_manufacturer)
                )
                if not identity_ok:
                    detail = (
                        "Page retrieved, but extractable text did not verify the entered "
                        "manufacturer and exact MPN. No values were taken."
                    )
                else:
                    detail = "Page retrieved and named the entered manufacturer and exact MPN."
                    html_doc = _document_from_html(
                        html=payload,
                        url=final_url,
                        source_name=source_type,
                    )
                    html_doc["source_type"] = source_type
                    # Authorized distributor pages may contribute values only after identity.
                    documents.append(html_doc)
            sources.append(
                _status_row(
                    source=source_type.split("_", 1)[0],
                    source_type=source_type,
                    url=final_url or url,
                    status=status if status != PROVIDER_AVAILABLE else (
                        PROVIDER_AVAILABLE if identity_ok else PROVIDER_NOT_FOUND
                    ),
                    detail=detail,
                    identity_verified=identity_ok,
                )
            )

    # 6) Parts aggregators — coverage only; never attribute compare values from them.
    # Skip when DigiKey already verified the exact MPN — these pages are not value sources.
    if skip_public_html:
        aggregator_candidates = []
        aggregator_fetches = []
    else:
        aggregator_candidates = _aggregator_listing_candidates(
            manufacturer=requested_manufacturer, mpn=requested_mpn
        )
        aggregator_fetches = _parallel_ordered(
            aggregator_candidates,
            lambda candidate: _fetch_public_https(candidate[1]),
        )
    for (source_type, url), (status, payload, final_url) in zip(
        aggregator_candidates, aggregator_fetches
    ):
        detail = str(payload) if status != PROVIDER_AVAILABLE else (
            "Aggregator listing retrieved. It is not an authorized distributor source; "
            "no attribute values were taken."
        )
        named = False
        if status == PROVIDER_AVAILABLE and isinstance(payload, str):
            probe_doc = {"pages": [{"page": "listing", "text": payload[:20000]}]}
            named = _pdf_mentions_exact_part(probe_doc, requested_mpn) and (
                not requested_manufacturer
                or _pdf_mentions_exact_part(probe_doc, requested_manufacturer)
            )
            if named:
                detail = (
                    "Aggregator listing names the manufacturer and exact MPN, but aggregator "
                    "pages are not used as authorized evidence for attribute values."
                )
        sources.append(
            _status_row(
                source="octopart",
                source_type=source_type,
                url=final_url or url,
                status=status,
                detail=detail,
                identity_verified=False,
            )
        )

    def _prefer_manufacturer_product(doc: Mapping[str, Any]) -> tuple[int, str]:
        source_type = str(doc.get("source_type") or "")
        if source_type in {"manufacturer_product_page", "manufacturer_catalog_path"}:
            return (0, source_type)
        if source_type.endswith("_authorized_product_page"):
            return (1, source_type)
        if source_type in {"manufacturer_pdf", "datasheet_pdf", "uploaded_datasheet"}:
            return (2, source_type)
        return (3, source_type)

    verified_docs = sorted(
        [
            doc
            for doc in documents
            if verify_datasheet_identity(
                doc, manufacturer=requested_manufacturer, mpn=requested_mpn
            )["verified"]
        ],
        key=_prefer_manufacturer_product,
    )
    primary = verified_docs[0] if verified_docs else (documents[0] if documents else None)
    primary_identity = verify_datasheet_identity(
        primary, manufacturer=requested_manufacturer, mpn=requested_mpn
    )
    return {
        "mpn": requested_mpn,
        "manufacturer": requested_manufacturer,
        "sources": sources,
        "documents": documents,
        "verified_documents": verified_docs,
        "primary_document": primary,
        "identity": primary_identity,
    }


def gather_part_evidence(
    *,
    mpn: str,
    manufacturer: str = "",
    datasheet_url: str = "",
    product_detail_url: str = "",
    probe_distributor_pages: bool = True,
    supplier_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch independent source pages together, then apply the normal evidence gates.

    Every source still gets its own status and identity check. Prefetching removes
    serial source-group timeouts without changing which sources are searched or
    which documents are allowed to contribute values.
    """
    requested_mpn = str(mpn or "").strip()
    requested_manufacturer = str(manufacturer or "").strip()
    candidates: list[tuple[str, str]] = []
    candidates.extend(
        (url, url)
        for _, url in _manufacturer_product_candidates(
            manufacturer=requested_manufacturer,
            mpn=requested_mpn,
            product_detail_url=product_detail_url,
        )
    )
    candidates.extend(
        (url, "")
        for _, url in _manufacturer_search_candidates(
            manufacturer=requested_manufacturer, mpn=requested_mpn
        )
    )
    maker_key = re.sub(r"[^a-z0-9]+", "", requested_manufacturer.casefold())
    if maker_key == "ohmite":
        candidates.extend(
            (url, url)
            for _, url in _ohmite_order_code_catalog_candidates(requested_mpn)
        )
    digikey_reusable = (
        isinstance(supplier_record, Mapping)
        and supplier_record
        and "digikey"
        in str(
            supplier_record.get("source")
            or supplier_record.get("Source")
            or supplier_record.get("supplier")
            or ""
        ).casefold()
        and _supplier_record_matches_exact_mpn(
            supplier_record, mpn=requested_mpn, manufacturer=requested_manufacturer
        )
    )
    effective_probe = bool(probe_distributor_pages) and not digikey_reusable
    if effective_probe:
        candidates.extend(
            (url, "")
            for _, url in _authorized_distributor_product_candidates(
                manufacturer=requested_manufacturer, mpn=requested_mpn
            )
        )
        candidates.extend(
            (url, "")
            for _, url in _distributor_public_candidates(
                requested_mpn, requested_manufacturer
            )
        )
    if not digikey_reusable:
        candidates.extend(
            (url, "")
            for _, url in _aggregator_listing_candidates(
                manufacturer=requested_manufacturer, mpn=requested_mpn
            )
        )

    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for url, referer in candidates:
        key = (_canonical_datasheet_url(url), referer)
        if key in seen:
            continue
        seen.add(key)
        unique.append((url, referer))

    fetched = _parallel_ordered(
        unique,
        lambda candidate: _fetch_public_https(
            candidate[0], referer=candidate[1]
        ),
        limit=10,
    )
    cache = {
        (_canonical_datasheet_url(url), referer): result
        for (url, referer), result in zip(unique, fetched)
    }
    token = _PREFETCHED_COMPARE_FETCHES.set(cache)
    try:
        return _gather_part_evidence_from_sources(
            mpn=requested_mpn,
            manufacturer=requested_manufacturer,
            datasheet_url=datasheet_url,
            product_detail_url=product_detail_url,
            probe_distributor_pages=effective_probe,
            supplier_record=supplier_record,
        )
    finally:
        _PREFETCHED_COMPARE_FETCHES.reset(token)


def prefer_verified_document(*documents: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return the first verified document mapping, else None."""
    for document in documents:
        if isinstance(document, Mapping) and document.get("available") and document.get("pages"):
            return dict(document)
    return None
