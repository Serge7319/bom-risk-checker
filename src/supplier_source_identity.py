"""Shared checks for distributor identity and official listing URLs."""
from __future__ import annotations

import re
from urllib.parse import urlsplit


_DOMAINS_BY_SUPPLIER = {
    "digikey": {
        "digikey.com", "digikey.ca", "digikey.co.uk", "digikey.de", "digikey.fr",
        "digikey.it", "digikey.jp", "digikey.kr", "digikey.in", "digikey.sg",
        "digikey.com.au",
    },
    "mouser": {"mouser.com"},
    "newark": {"newark.com", "newark.com.cn", "element14.com", "farnell.com"},
    "nexarsupply": {"nexar.com", "octopart.com"},
}


def canonical_supplier_key(value: object) -> str:
    compact = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    aliases = {
        "digikeyelectronics": "digikey",
        "mouserelectronics": "mouser",
        "nexar": "nexarsupply",
        "octopart": "nexarsupply",
        "element14": "newark",
        "farnell": "newark",
    }
    return aliases.get(compact, compact)


def is_supported_distributor(value: object) -> bool:
    return canonical_supplier_key(value) in _DOMAINS_BY_SUPPLIER


def supplier_listing_url_is_valid(supplier: object, value: object) -> bool:
    """Require HTTPS, no userinfo, and a host owned by the named distributor."""
    try:
        parsed = urlsplit(str(value or "").strip())
        host = (parsed.hostname or "").rstrip(".").casefold()
    except ValueError:
        return False
    if parsed.scheme.casefold() != "https" or not host or parsed.username or parsed.password:
        return False
    domains = _DOMAINS_BY_SUPPLIER.get(canonical_supplier_key(supplier), set())
    return any(host == domain or host.endswith("." + domain) for domain in domains)
