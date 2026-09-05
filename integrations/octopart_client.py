"""Exact-match Octopart component intelligence through the Nexar Supply API."""
from __future__ import annotations

import re
import threading
import time
from typing import Any

import requests

from integrations.stock_coercion import coerce_stock_total

from src.secrets import get_secret


TOKEN_URL = "https://identity.nexar.com/connect/token"
GRAPHQL_URL = "https://api.nexar.com/graphql"
# Official Nexar Supply API client-credentials scope (required for supSearch*).
NEXAR_TOKEN_SCOPE = "supply.domain"
REQUEST_TIMEOUT_SECONDS = 15
DEFAULT_SEARCH_LIMIT = 5
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, object] = {}

# Subreasons for structured Alternative Finder diagnostics (never include secrets).
SUBREASON_GRAPHQL_ERRORS = "graphql_errors"
SUBREASON_EMPTY_RESPONSE = "empty_response"
SUBREASON_MALFORMED_RESPONSE = "malformed_response"
SUBREASON_MISSING_EXPECTED_DATA = "missing_expected_data"
SUBREASON_SCHEMA_MISMATCH = "schema_mismatch"
SUBREASON_AUTHENTICATION = "authentication"
SUBREASON_RATE_LIMIT = "rate_limit"
SUBREASON_PROVIDER_FAILURE = "provider_failure"
SUBREASON_ZERO_RESULTS = "zero_results"
SUBREASON_OK = "ok"

# Safe GraphQL error taxonomy for diagnostics/tests (never message bodies).
GRAPHQL_KIND_AUTH = "auth"
GRAPHQL_KIND_SCHEMA = "schema"
GRAPHQL_KIND_RATE_LIMIT = "rate_limit"
GRAPHQL_KIND_PROVIDER = "provider"
GRAPHQL_KIND_OTHER = "other"

# Canonical Nexar Supply MPN search — modeled on official Nexar examples.
# Do not add undocumented fields; do not invent parallel query strings.
CANONICAL_SUP_SEARCH_MPN_QUERY = """
query SearchMpn($mpn: String!, $limit: Int!) {
  supSearchMpn(q: $mpn, limit: $limit) {
    hits
    results {
      description
      part {
        mpn
        manufacturer {
          name
        }
        sellers {
          company {
            name
          }
          offers {
            inventoryLevel
            prices {
              quantity
              price
            }
          }
        }
      }
    }
  }
}
""".strip()

# Back-compat alias for existing imports/tests; always the canonical query.
_PART_QUERY = CANONICAL_SUP_SEARCH_MPN_QUERY

# Fields that must never appear in the emitted canonical query.
_UNSUPPORTED_QUERY_MARKERS = (
    "clickUrl",
    "shortDescription",
    "currency:",
    "country:",
    "authorizedOnly",
    "includeBrokers",
    "octopartUrl",
    "factoryLeadDays",
    "similarParts",
)


def canonical_sup_search_mpn_query() -> str:
    """Return the single official Nexar Supply MPN search query string."""
    return CANONICAL_SUP_SEARCH_MPN_QUERY


def build_nexar_sup_search_mpn_request(
    mpn: str, *, limit: int = DEFAULT_SEARCH_LIMIT
) -> dict[str, Any]:
    """Build the only Octopart/Nexar GraphQL request body used by Cadivor."""
    try:
        resolved_limit = int(limit)
    except (TypeError, ValueError):
        resolved_limit = DEFAULT_SEARCH_LIMIT
    if resolved_limit < 1:
        resolved_limit = DEFAULT_SEARCH_LIMIT
    return {
        "query": CANONICAL_SUP_SEARCH_MPN_QUERY,
        "variables": {
            "mpn": str(mpn or "").strip(),
            "limit": resolved_limit,
        },
    }


def nexar_authorization_headers(access_token: str) -> dict[str, str]:
    """Documented Nexar HTTP authorization: Authorization: Bearer <access token>."""
    return {"Authorization": f"Bearer {str(access_token or '').strip()}"}


def query_contains_unsupported_fields(query: str) -> list[str]:
    """Return unsupported markers found in a query (for contract tests)."""
    text = str(query or "")
    return [marker for marker in _UNSUPPORTED_QUERY_MARKERS if marker in text]

_REJECTED_FIELD_PATTERNS = (
    re.compile(r"Cannot query field ['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"Unknown (?:field|argument) ['\"]([^'\"]+)['\"]", re.IGNORECASE),
    re.compile(r"Field ['\"]([^'\"]+)['\"] is not defined", re.IGNORECASE),
    re.compile(r"Field ['\"]([^'\"]+)['\"] doesn't exist", re.IGNORECASE),
    re.compile(r"Argument ['\"]([^'\"]+)['\"] has invalid value", re.IGNORECASE),
    re.compile(r"got invalid value .+ for argument ['\"]([^'\"]+)['\"]", re.IGNORECASE),
)

_AUTH_ERROR_CODES = frozenset(
    {
        "unauthenticated",
        "unauthorized",
        "forbidden",
        "access_denied",
        "accessdenied",
        "insufficient_scope",
        "insufficientscope",
        "permission_denied",
        "permissiondenied",
    }
)

_RATE_LIMIT_ERROR_CODES = frozenset(
    {
        "rate_limited",
        "ratelimited",
        "too_many_requests",
        "throttled",
        "throttle",
    }
)


class OctopartResponseError(RuntimeError):
    """Configured Octopart/Nexar call failed with a classified response subreason."""

    def __init__(
        self,
        message: str,
        *,
        subreason: str,
        rejected_fields: list[str] | tuple[str, ...] | None = None,
        error_codes: list[str] | tuple[str, ...] | None = None,
        graphql_kind: str = "",
        error_fingerprint: str = "",
        error_count: int = 0,
    ):
        super().__init__(message)
        self.subreason = str(subreason or SUBREASON_MALFORMED_RESPONSE).strip()
        self.rejected_fields = tuple(
            str(item).strip()
            for item in (rejected_fields or ())
            if str(item or "").strip()
        )
        self.error_codes = tuple(
            str(item).strip()
            for item in (error_codes or ())
            if str(item or "").strip()
        )
        self.graphql_kind = str(graphql_kind or "").strip()
        self.error_fingerprint = str(error_fingerprint or "").strip()
        try:
            self.error_count = max(int(error_count or 0), 0)
        except (TypeError, ValueError):
            self.error_count = 0


def _nexar_secret(primary_name: str, legacy_name: str) -> str:
    """Resolve the current Nexar key, then the pre-standardization alias."""
    value = get_secret(primary_name, default=None)
    if value:
        return str(value)
    return str(get_secret(legacy_name, required=True))


def _access_token() -> str:
    # Some Railway deployments were configured before the Nexar naming was
    # standardized. Continue accepting those variable names so a working
    # Octopart credential is not silently disconnected by a code upgrade.
    client_id = _nexar_secret("NEXAR_CLIENT_ID", "OCTOPART_CLIENT_ID")
    client_secret = _nexar_secret("NEXAR_CLIENT_SECRET", "OCTOPART_CLIENT_SECRET")
    with _TOKEN_LOCK:
        if (
            _TOKEN_CACHE.get("client_id") == client_id
            and _TOKEN_CACHE.get("scope") == NEXAR_TOKEN_SCOPE
            and float(_TOKEN_CACHE.get("expires_at", 0)) > time.monotonic() + 60
        ):
            return str(_TOKEN_CACHE["access_token"])

        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": NEXAR_TOKEN_SCOPE,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise OctopartResponseError(
                "Octopart authentication returned a malformed token payload.",
                subreason=SUBREASON_MALFORMED_RESPONSE,
            ) from exc
        if not isinstance(payload, dict):
            raise OctopartResponseError(
                "Octopart authentication returned a malformed token payload.",
                subreason=SUBREASON_MALFORMED_RESPONSE,
            )
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("Octopart authentication returned no usable credential.")
        # Token may succeed while omitting Supply scope; treat that as auth failure
        # before any GraphQL call so diagnostics stay actionable.
        granted_scope = str(payload.get("scope") or "").strip().casefold()
        if granted_scope and NEXAR_TOKEN_SCOPE not in {
            part.strip() for part in granted_scope.replace(",", " ").split()
        }:
            raise OctopartResponseError(
                "Octopart authentication returned a token without Supply API scope.",
                subreason=SUBREASON_AUTHENTICATION,
                error_codes=["insufficient_scope"],
                graphql_kind=GRAPHQL_KIND_AUTH,
            )
        try:
            expires_in = max(int(payload.get("expires_in", 3600)), 1)
        except (TypeError, ValueError):
            expires_in = 3600
        _TOKEN_CACHE.update(
            client_id=client_id,
            scope=NEXAR_TOKEN_SCOPE,
            access_token=access_token,
            expires_at=time.monotonic() + expires_in,
        )
        return access_token


def default_octopart_result(part_number: str = "") -> dict:
    return {
        "source": "Octopart",
        "manufacturer_part_number": "",
        "manufacturer": "",
        "description": "",
        "lifecycle_status": "Unknown",
        "stock_total": 0,
        "supplier_count": 0,
        "unit_price": 0.0,
        "lead_time_weeks": None,
        "has_alternates": False,
        "product_detail_url": "",
        "datasheet_url": "",
        "mouser_part_number": "",
        "package": "",
        "pin_count": 0,
        "mounting_style": "",
        "voltage_range": "",
        "architecture": "",
        "channel_count": 0,
        "supply_voltage_min": None,
        "supply_voltage_max": None,
        "octopart_sellers": [],
        "octopart_subreason": "",
        "octopart_hits": 0,
    }


def _normalize_search_result(result_row: dict) -> dict:
    """Normalize one canonical `supSearchMpn.results[]` row into Cadivor fields."""
    part = result_row.get("part") if isinstance(result_row.get("part"), dict) else {}
    result = default_octopart_result()
    result["manufacturer_part_number"] = str(part.get("mpn") or "").strip()
    manufacturer = part.get("manufacturer") or {}
    result["manufacturer"] = (
        str(manufacturer.get("name") or "") if isinstance(manufacturer, dict) else ""
    )
    # Official query exposes description on the search result, not on part.
    result["description"] = str(result_row.get("description") or "").strip()

    seller_names = set()
    prices = []
    for seller in part.get("sellers") or []:
        if not isinstance(seller, dict):
            continue
        company = seller.get("company") or {}
        seller_name = (
            str(company.get("name") or "").strip() if isinstance(company, dict) else ""
        )
        if seller_name:
            seller_names.add(seller_name)
        for offer in seller.get("offers") or []:
            if not isinstance(offer, dict):
                continue
            try:
                result["stock_total"] += coerce_stock_total(offer.get("inventoryLevel"))
            except (TypeError, ValueError):
                pass
            for tier in offer.get("prices") or []:
                if not isinstance(tier, dict):
                    continue
                try:
                    quantity = int(tier.get("quantity") or 1)
                    price = float(tier.get("price"))
                    if price > 0:
                        prices.append((quantity, price))
                except (TypeError, ValueError):
                    continue

    result["octopart_sellers"] = sorted(seller_names)
    result["supplier_count"] = len(seller_names)
    if prices:
        smallest_quantity = min(quantity for quantity, _ in prices)
        result["unit_price"] = min(
            price for quantity, price in prices if quantity == smallest_quantity
        )
    result["octopart_subreason"] = SUBREASON_OK
    return result


def _normalize_part(part: dict) -> dict:
    """Back-compat wrapper: treat a bare part dict as a search result without description."""
    return _normalize_search_result({"part": part, "description": ""})


def extract_graphql_rejected_fields(errors: list[Any] | None) -> list[str]:
    """Extract rejected GraphQL field/argument names only (safe for diagnostics/tests)."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        cleaned = str(name or "").strip()
        if not cleaned or cleaned in seen:
            return
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cleaned):
            return
        if cleaned in {"query", "mutation", "subscription", "data"}:
            return
        seen.add(cleaned)
        found.append(cleaned)

    for item in errors or []:
        message = ""
        if isinstance(item, dict):
            message = str(item.get("message") or "")
            path = item.get("path")
            if isinstance(path, list) and path:
                leaf = path[-1]
                if isinstance(leaf, str):
                    _add(leaf)
            extensions = item.get("extensions")
            if isinstance(extensions, dict):
                for key in ("fieldName", "argumentName", "field", "argument"):
                    _add(str(extensions.get(key) or ""))
        else:
            message = str(item or "")
        for pattern in _REJECTED_FIELD_PATTERNS:
            for match in pattern.finditer(message):
                _add(str(match.group(1) or ""))
    return found


def extract_graphql_error_codes(errors: list[Any] | None) -> list[str]:
    """Extract safe GraphQL error codes (no messages/bodies)."""
    codes: list[str] = []
    seen: set[str] = set()
    for item in errors or []:
        if not isinstance(item, dict):
            continue
        extensions = item.get("extensions")
        raw = ""
        if isinstance(extensions, dict):
            raw = str(extensions.get("code") or "").strip()
        if not raw:
            raw = str(item.get("code") or "").strip()
        if not raw or raw in seen:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", raw):
            continue
        seen.add(raw)
        codes.append(raw)
    return codes


def graphql_error_fingerprint(errors: list[Any] | None) -> str:
    """Stable non-sensitive fingerprint for unknown GraphQL failures.

    Never includes raw messages, URLs, tokens, or response bodies — only a
    short hash of normalized shape signals (length bucket + token stubs).
    """
    import hashlib

    parts: list[str] = []
    for item in errors or []:
        if isinstance(item, dict):
            message = str(item.get("message") or "")
            code = ""
            extensions = item.get("extensions")
            if isinstance(extensions, dict):
                code = str(extensions.get("code") or "").strip()
            path = item.get("path")
            path_depth = len(path) if isinstance(path, list) else 0
        else:
            message = str(item or "")
            code = ""
            path_depth = 0
        normalized = re.sub(r"[^a-z0-9]+", " ", message.casefold()).strip()
        tokens = [tok for tok in normalized.split() if tok and len(tok) <= 24][:6]
        # Keep only short alphabetic stubs; drop anything that looks like an id/url.
        stubs = [tok for tok in tokens if tok.isalpha() and 2 <= len(tok) <= 12][:4]
        length_bucket = min(len(normalized) // 16, 15)
        parts.append(
            f"c={code.casefold()[:32]}|d={path_depth}|l={length_bucket}|t={'-'.join(stubs)}"
        )
    if not parts:
        return ""
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"gql_{len(parts)}_{digest}"


def _graphql_messages(errors: list[Any]) -> str:
    snippets: list[str] = []
    for item in errors:
        if isinstance(item, dict):
            snippets.append(str(item.get("message") or ""))
        else:
            snippets.append(str(item or ""))
    return " ".join(snippets).casefold()


def _is_rate_limit_graphql_failure(errors: list[Any]) -> bool:
    codes = {code.casefold().replace("-", "_") for code in extract_graphql_error_codes(errors)}
    if codes & _RATE_LIMIT_ERROR_CODES:
        return True
    joined = _graphql_messages(errors)
    return (
        "rate limit" in joined
        or "too many requests" in joined
        or "throttl" in joined
        or "429" in joined
    )


def _is_auth_graphql_failure(errors: list[Any]) -> bool:
    codes = {code.casefold().replace("-", "_") for code in extract_graphql_error_codes(errors)}
    if codes & _AUTH_ERROR_CODES:
        return True
    joined = _graphql_messages(errors)
    markers = (
        "not authenticated",
        "unauthenticated",
        "unauthorized",
        "access denied",
        "permission denied",
        "forbidden",
        "insufficient scope",
        "invalid scope",
        "missing scope",
        "required scope",
        "not authorized",
        "authorization required",
        "authentication required",
        "invalid token",
        "token expired",
        "jwt expired",
        "jwt invalid",
        "not entitled",
        "entitlement",
        "access control",
        "supply.domain",
        "supply api",
    )
    return any(marker in joined for marker in markers)


def _is_provider_graphql_failure(errors: list[Any]) -> bool:
    """Known safe provider-side failure wording (never treat as schema/auth)."""
    codes = {code.casefold().replace("-", "_") for code in extract_graphql_error_codes(errors)}
    if codes & {
        "internal_server_error",
        "internal",
        "server_error",
        "bad_gateway",
        "service_unavailable",
        "upstream_error",
        "provider_error",
    }:
        return True
    joined = _graphql_messages(errors)
    markers = (
        "temporarily unavailable",
        "upstream supplier",
        "upstream error",
        "upstream service",
        "internal server",
        "internal error",
        "server error",
        "service unavailable",
        "bad gateway",
        "try again later",
        "provider error",
        "backend error",
    )
    return any(marker in joined for marker in markers)


def _is_schema_graphql_failure(errors: list[Any]) -> bool:
    if extract_graphql_rejected_fields(errors):
        return True
    joined = _graphql_messages(errors)
    codes = {code.casefold() for code in extract_graphql_error_codes(errors)}
    if "graphql_validation_failed" in codes or "validation" in " ".join(codes):
        schema_markers = (
            "cannot query field",
            "unknown field",
            "unknown argument",
            "field undefined",
            "is not defined",
            "doesn't exist",
            "does not exist",
            "has invalid value",
            "got invalid value",
            "expected type",
            "must not have a selection",
            "did you mean",
        )
        if any(marker in joined for marker in schema_markers):
            return True
        if not _is_auth_graphql_failure(errors) and not _is_rate_limit_graphql_failure(errors):
            return True
    return (
        "cannot query field" in joined
        or "unknown field" in joined
        or "unknown argument" in joined
        or "field undefined" in joined
        or "is not defined by type" in joined
        or "doesn't exist" in joined
        or "does not exist" in joined
        or "has invalid value" in joined
        or "got invalid value" in joined
    )


def graphql_error_kind(errors: list[Any] | None) -> str:
    """Classify GraphQL errors into a safe kind label for diagnostics."""
    items = list(errors or [])
    if not items:
        return GRAPHQL_KIND_OTHER
    if _is_auth_graphql_failure(items):
        return GRAPHQL_KIND_AUTH
    if _is_rate_limit_graphql_failure(items):
        return GRAPHQL_KIND_RATE_LIMIT
    if _is_schema_graphql_failure(items):
        return GRAPHQL_KIND_SCHEMA
    if _is_provider_graphql_failure(items):
        return GRAPHQL_KIND_PROVIDER
    return GRAPHQL_KIND_OTHER


def inspect_nexar_graphql_errors(errors: list[Any] | None) -> dict[str, Any]:
    """Controlled diagnostic helper for fixtures/tests — never logs secrets or bodies."""
    rejected_fields = extract_graphql_rejected_fields(errors)
    error_codes = extract_graphql_error_codes(errors)
    kind = graphql_error_kind(errors)
    fingerprint = ""
    # Auth/schema get explicit labels; everything else gets a safe fingerprint only.
    if kind in {GRAPHQL_KIND_OTHER, GRAPHQL_KIND_PROVIDER}:
        fingerprint = graphql_error_fingerprint(errors)
    return {
        "error_count": len(errors or []),
        "rejected_fields": rejected_fields,
        "error_codes": error_codes,
        "graphql_kind": kind,
        "error_fingerprint": fingerprint,
        "subreason": _graphql_error_subreason(errors or []),
    }


def _graphql_error_subreason(errors: list[Any]) -> str:
    kind = graphql_error_kind(errors)
    if kind == GRAPHQL_KIND_AUTH:
        return SUBREASON_AUTHENTICATION
    if kind == GRAPHQL_KIND_RATE_LIMIT:
        return SUBREASON_RATE_LIMIT
    if kind == GRAPHQL_KIND_SCHEMA:
        return SUBREASON_SCHEMA_MISMATCH
    if kind == GRAPHQL_KIND_PROVIDER:
        return SUBREASON_PROVIDER_FAILURE
    return SUBREASON_GRAPHQL_ERRORS


def classify_nexar_graphql_payload(payload: Any) -> dict[str, Any]:
    """Classify a Nexar GraphQL JSON body without logging secrets or bodies."""
    empty = {
        "subreason": SUBREASON_EMPTY_RESPONSE,
        "hits": 0,
        "results": [],
        "usable": False,
        "rejected_fields": [],
        "error_codes": [],
        "graphql_kind": GRAPHQL_KIND_OTHER,
        "error_fingerprint": "",
        "error_count": 0,
    }
    if payload is None or payload == "":
        return dict(empty)
    if not isinstance(payload, dict):
        return {
            **empty,
            "subreason": SUBREASON_MALFORMED_RESPONSE,
        }
    if not payload:
        return dict(empty)

    errors = payload.get("errors")
    has_errors = isinstance(errors, list) and bool(errors)
    rejected_fields = extract_graphql_rejected_fields(errors if has_errors else [])
    error_codes = extract_graphql_error_codes(errors if has_errors else [])
    kind = graphql_error_kind(errors if has_errors else [])
    error_count = len(errors) if has_errors else 0
    fingerprint = ""
    if has_errors and kind in {GRAPHQL_KIND_OTHER, GRAPHQL_KIND_PROVIDER}:
        fingerprint = graphql_error_fingerprint(errors)
    data = payload.get("data")

    def _fail(subreason: str) -> dict[str, Any]:
        return {
            "subreason": subreason,
            "hits": 0,
            "results": [],
            "usable": False,
            "rejected_fields": rejected_fields,
            "error_codes": error_codes,
            "graphql_kind": kind if has_errors else GRAPHQL_KIND_OTHER,
            "error_fingerprint": fingerprint if has_errors else "",
            "error_count": error_count,
        }

    if has_errors and data in (None, {}):
        return _fail(_graphql_error_subreason(errors))

    if data is None and not has_errors:
        return _fail(SUBREASON_EMPTY_RESPONSE)

    if not isinstance(data, dict):
        return _fail(SUBREASON_MALFORMED_RESPONSE)

    if "supSearchMpn" not in data:
        if has_errors:
            return _fail(_graphql_error_subreason(errors if isinstance(errors, list) else []))
        return _fail(SUBREASON_MISSING_EXPECTED_DATA)

    search = data.get("supSearchMpn")
    if search is None:
        return {
            "subreason": SUBREASON_ZERO_RESULTS,
            "hits": 0,
            "results": [],
            "usable": True,
            "rejected_fields": [],
            "error_codes": [],
            "graphql_kind": GRAPHQL_KIND_OTHER,
            "error_fingerprint": "",
            "error_count": 0,
        }
    if not isinstance(search, dict):
        return _fail(SUBREASON_MALFORMED_RESPONSE)

    results = search.get("results")
    if results is None:
        results = []
    if not isinstance(results, list):
        return _fail(SUBREASON_MALFORMED_RESPONSE)

    try:
        hits = int(search.get("hits") if search.get("hits") is not None else len(results))
    except (TypeError, ValueError):
        hits = len(results)

    if not results:
        if has_errors:
            return {
                **_fail(_graphql_error_subreason(errors if isinstance(errors, list) else [])),
                "hits": hits,
            }
        return {
            "subreason": SUBREASON_ZERO_RESULTS,
            "hits": hits,
            "results": [],
            "usable": True,
            "rejected_fields": [],
            "error_codes": [],
            "graphql_kind": GRAPHQL_KIND_OTHER,
            "error_fingerprint": "",
            "error_count": 0,
        }

    if has_errors and not results:
        return _fail(_graphql_error_subreason(errors if isinstance(errors, list) else []))

    return {
        "subreason": SUBREASON_OK,
        "hits": hits,
        "results": results,
        "usable": True,
        "rejected_fields": rejected_fields,
        "error_codes": error_codes,
        "graphql_kind": kind,
        "error_fingerprint": "",
        "error_count": error_count,
    }


def _exact_match_result(requested: str, results: list[Any]) -> dict | None:
    """Return the canonical results[] row whose part.mpn exactly matches."""
    requested_key = re.sub(r"[^a-z0-9]", "", requested.casefold())
    for candidate in results:
        if not isinstance(candidate, dict):
            continue
        part = candidate.get("part") or {}
        if not isinstance(part, dict):
            continue
        candidate_key = re.sub(
            r"[^a-z0-9]", "", str(part.get("mpn") or "").strip().casefold()
        )
        if candidate_key and candidate_key == requested_key:
            return candidate
    return None


def search_octopart_by_part_number(part_number: str) -> dict:
    """Lookup via the single canonical Nexar Supply SearchMpn query."""
    requested = str(part_number or "").strip()
    if not requested:
        empty = default_octopart_result()
        empty["octopart_subreason"] = SUBREASON_ZERO_RESULTS
        return empty

    response = requests.post(
        GRAPHQL_URL,
        json=build_nexar_sup_search_mpn_request(requested),
        headers=nexar_authorization_headers(_access_token()),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        status_code = int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        status_code = 0
    if status_code in {401, 403}:
        raise OctopartResponseError(
            "Octopart supplier query was rejected by authentication.",
            subreason=SUBREASON_AUTHENTICATION,
            error_codes=[str(status_code)],
            graphql_kind=GRAPHQL_KIND_AUTH,
        )
    if status_code == 429:
        raise OctopartResponseError(
            "Octopart supplier query was rate limited.",
            subreason=SUBREASON_RATE_LIMIT,
            error_codes=["429"],
            graphql_kind=GRAPHQL_KIND_RATE_LIMIT,
        )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise OctopartResponseError(
            "Octopart supplier query returned a malformed response.",
            subreason=SUBREASON_MALFORMED_RESPONSE,
        ) from exc

    classified = classify_nexar_graphql_payload(payload)
    subreason = str(classified.get("subreason") or SUBREASON_MALFORMED_RESPONSE)
    if not classified.get("usable"):
        raise OctopartResponseError(
            "Octopart supplier query could not be completed.",
            subreason=subreason,
            rejected_fields=list(classified.get("rejected_fields") or []),
            error_codes=list(classified.get("error_codes") or []),
            graphql_kind=str(classified.get("graphql_kind") or ""),
            error_fingerprint=str(classified.get("error_fingerprint") or ""),
            error_count=int(classified.get("error_count") or 0),
        )

    results = list(classified.get("results") or [])
    hits = int(classified.get("hits") or 0)
    matched = _exact_match_result(requested, results)
    if matched is not None:
        normalized = _normalize_search_result(matched)
        normalized["octopart_hits"] = hits
        return normalized

    # Valid data with hits=0 or no exact MPN match → PART_NOT_FOUND / zero_results.
    empty = default_octopart_result(requested)
    empty["octopart_subreason"] = SUBREASON_ZERO_RESULTS
    empty["octopart_hits"] = hits
    return empty
