from concurrent.futures import ThreadPoolExecutor, as_completed
import re

from src.runtime_cache import cache_data

from integrations.pin_count import sanitize_stored_pin_count
from integrations.stock_coercion import parse_stock_total
from integrations.provider_health import (
    PROVIDER_AVAILABLE,
    PROVIDER_ERROR,
    PROVIDER_NOT_CONFIGURED,
    PROVIDER_PART_NOT_FOUND,
    classify_provider_exception,
    sanitize_provider_message,
    summarize_provider_health,
)
from integrations.mouser_client import search_mouser_by_part_number
try:
    from integrations.mouser_client import search_mouser_catalog_candidates
except ImportError:
    def search_mouser_catalog_candidates(
        part_number,
        *,
        limit=12,
        include_family_search=True,
    ):
        return []
from integrations.digikey_client import search_digikey_by_part_number
try:
    from integrations.digikey_client import (
        search_digikey_catalog_candidates,
        search_digikey_substitutions,
    )
except ImportError:
    def search_digikey_substitutions(part_number: str) -> list[dict]:
        return []

    def search_digikey_catalog_candidates(
        part_number: str,
        *,
        include_family_search: bool = True,
        additional_search_terms: list[str] | None = None,
    ) -> list[dict]:
        return []
from src.alternative_classification import merge_discovery_candidates, utc_now_iso
from src.secrets import get_secret
from src.part_images import normalize_supplier_image_url
from src.normalizer import normalize_part_number

try:
    from integrations.newark_client import search_newark_by_part_number
    try:
        from integrations.newark_client import search_newark_catalog_candidates
    except ImportError:
        def search_newark_catalog_candidates(
            part_number,
            *,
            limit=12,
            include_family_search=True,
        ):
            return []
except ImportError as newark_import_error:
    _newark_import_error = newark_import_error

    def search_newark_by_part_number(part_number):
        raise RuntimeError("Newark supplier integration could not be loaded.") from _newark_import_error

    def search_newark_catalog_candidates(
        part_number,
        *,
        limit=12,
        include_family_search=True,
    ):
        raise RuntimeError("Newark supplier integration could not be loaded.") from _newark_import_error

try:
    from integrations.nexar_client import search_nexar_by_part_number
except ImportError as nexar_import_error:
    _nexar_import_error = nexar_import_error

    def search_nexar_by_part_number(part_number):
        raise RuntimeError("Nexar Supply integration could not be loaded.") from _nexar_import_error


def _empty_supplier_result(source_name: str, *, provider_status: str, error: str = "") -> dict:
    return {
        "source": source_name,
        "provider_status": provider_status,
        "error": error,
        "lifecycle_status": "Unknown",
        "stock_total": None,
        "supplier_count": None,
        "lead_time_weeks": None,
        "unit_price": 0.0,
        "has_alternates": False,
        "manufacturer": "",
        "description": "",
        "mouser_part_number": "",
        "manufacturer_part_number": "",
        "product_detail_url": "",
        "image_url": "",
        "datasheet_url": "",
        "package": "",
        "pin_count": 0,
        "mounting_style": "",
        "voltage_range": "",
        "architecture": "",
        "channel_count": 0,
        "supply_voltage_min": None,
        "supply_voltage_max": None,
        "bandwidth_mhz": None,
        "slew_rate_v_us": None,
    }


def _supplier_result_matches_request(source_name: str, requested: str, result: dict) -> bool:
    """Reject ranked/fuzzy results unless the returned identity matches the BOM MPN.

    Supplier-specific order numbers remain valid when the user entered that
    distributor number. A neighboring catalog result must never lend its stock
    or lifecycle status to the requested component.
    """
    requested_key = normalize_part_number(str(requested or "").strip())
    if not requested_key:
        return False
    returned_mpn = normalize_part_number(str(result.get("manufacturer_part_number") or "").strip())
    if returned_mpn and returned_mpn == requested_key:
        return True
    distributor_fields = {
        "DigiKey": ("digikey_part_number", "order_part_number"),
        "Mouser": ("mouser_part_number",),
        "Newark": ("newark_part_number", "element14_part_number"),
    }.get(str(source_name), ())
    return any(
        normalize_part_number(str(result.get(field) or "").strip()) == requested_key
        for field in distributor_fields
        if result.get(field)
    )


def _supplier_query_variants(part_number: object) -> tuple[str, ...]:
    """Try only case and separator formatting; never strip MPN suffixes.

    Distributors often index AMD flash order codes with a hyphen before the
    speed/package grade (AM29F010B-70EC). When the BOM omits that hyphen,
    retry the hyphenated form so exact identity can still resolve.
    """
    import re

    raw = str(part_number or "").strip()
    variants: list[str] = []

    def _add(value: object) -> None:
        candidate = str(value or "").strip()
        if candidate and candidate not in variants:
            variants.append(candidate)

    _add(raw)
    _add(raw.upper())
    compact = normalize_part_number(raw)
    _add(compact)
    if compact and "-" not in raw:
        # AM29F010B70EC → AM29F010B-70EC (speed/temp/package digit run).
        hyphenated = re.sub(
            r"([A-Za-z])(\d{2,}[A-Za-z]{0,4})$",
            r"\1-\2",
            compact,
            count=1,
        )
        _add(hyphenated)
        # IRF540N → IRF-540N style letter→digit boundary (first only).
        boundary = re.sub(r"([A-Za-z])(\d)", r"\1-\2", compact, count=1)
        _add(boundary)
    return tuple(variants)


def _canonical_lifecycle(status: object) -> str:
    text = " ".join(str(status or "").strip().casefold().replace("_", " ").split())
    if not text or text in {"unknown", "unverified", "n/a", "not available"}:
        return ""
    if any(term in text for term in ("obsolete", "end of life", "eol", "discontinued")):
        return "Obsolete"
    if "nrnd" in text or "not recommended" in text:
        return "NRND"
    if "replacement suggested" in text or "suggested replacement" in text:
        return "Replacement Suggested"
    if text in {"active", "in production", "production"}:
        return "Active"
    return str(status).strip()


def _resolve_lifecycle(results: list[dict]) -> tuple[str, list[dict], bool]:
    evidence = []
    for result in results:
        raw = str(result.get("lifecycle_status") or "").strip()
        canonical = _canonical_lifecycle(raw)
        if canonical:
            evidence.append({
                "source": str(result.get("source") or "Supplier"),
                "status": raw,
                "normalized_status": canonical,
                "retrieved_at": result.get("retrieved_at"),
            })
    statuses = {row["normalized_status"] for row in evidence}
    if len(statuses) > 1:
        return "Conflicting supplier data", evidence, True
    if statuses:
        return next(iter(statuses)), evidence, False
    return "Unknown", evidence, False


def _invoke_supplier_lookup(
    lookup_func,
    part_number: str,
    *,
    source_name: str = "",
    manufacturer: str = "",
):
    """Call a supplier lookup, passing manufacturer only where supported.

    DigiKey workers run in a ThreadPoolExecutor, so manufacturer must be an
    explicit argument — ContextVar values from the parent thread do not apply.
    """
    requested_mfr = str(manufacturer or "").strip()
    if requested_mfr and str(source_name or "") == "DigiKey":
        try:
            return lookup_func(part_number, manufacturer=requested_mfr)
        except TypeError:
            # Stubs / older callables may only accept the part number.
            pass
    return lookup_func(part_number)


def _safe_supplier_lookup(
    source_name,
    lookup_func,
    part_number,
    request_id: str = "",
    manufacturer: str = "",
):
    from integrations.supplier_diagnostics import (
        attach_supplier_diagnostic,
        resolve_supplier_diagnostic_request_id,
        log_supplier_diagnostic,
    )
    from src.performance_timing import (
        emit_timing,
        normalize_provider,
        supplier_outcome_from_status,
        timing_enabled,
    )
    import time as _time

    # Resolve once; do not mutate the process-wide AF request-id stack from worker
    # threads (concurrent set/reset would race). Pass the id explicitly to logs.
    resolved_request_id = resolve_supplier_diagnostic_request_id(request_id)
    requested_mfr = str(manufacturer or "").strip()

    started = _time.perf_counter() if timing_enabled() else None
    try:
        if lookup_func is None:
            result = _empty_supplier_result(
                source_name,
                provider_status=PROVIDER_NOT_CONFIGURED,
                error=f"{source_name} is not configured",
            )
            diagnostic = log_supplier_diagnostic(
                request_id=resolved_request_id,
                supplier=str(source_name),
                stage="lookup",
                provider_status=PROVIDER_NOT_CONFIGURED,
                error_message=result.get("error", ""),
            )
            attach_supplier_diagnostic(result, diagnostic)
            if started is not None:
                emit_timing(
                    "supplier.lookup",
                    duration_ms=round((_time.perf_counter() - started) * 1000.0, 1),
                    outcome="unavailable",
                    provider=normalize_provider(source_name),
                    operation="lookup",
                )
            return result

        result = None
        last_nonmatching_result = None
        for query_variant in _supplier_query_variants(part_number):
            candidate_result = _invoke_supplier_lookup(
                lookup_func,
                query_variant,
                source_name=str(source_name or ""),
                manufacturer=requested_mfr,
            )
            if not candidate_result:
                continue
            if candidate_result.get("error"):
                result = candidate_result
                break
            if _supplier_result_matches_request(
                source_name, part_number, candidate_result
            ):
                result = candidate_result
                break
            last_nonmatching_result = candidate_result
        if result is None:
            result = last_nonmatching_result

        if not result:
            result = _empty_supplier_result(
                source_name,
                provider_status=PROVIDER_ERROR,
                error=f"No response from {source_name}",
            )
            diagnostic = log_supplier_diagnostic(
                request_id=resolved_request_id,
                supplier=str(source_name),
                stage="lookup",
                provider_status=PROVIDER_ERROR,
                error_message=result.get("error", ""),
            )
            attach_supplier_diagnostic(result, diagnostic)
            if started is not None:
                emit_timing(
                    "supplier.lookup",
                    duration_ms=round((_time.perf_counter() - started) * 1000.0, 1),
                    outcome="error",
                    provider=normalize_provider(source_name),
                    operation="lookup",
                )
            return result

        result["source"] = source_name
        result.setdefault("package", "")
        result.setdefault("pin_count", 0)
        result.setdefault("mounting_style", "")
        result.setdefault("image_url", "")
        result.setdefault("datasheet_url", "")
        result.setdefault("voltage_range", "")
        result.setdefault("architecture", "")
        result.setdefault("channel_count", 0)
        result.setdefault("supply_voltage_min", None)
        result.setdefault("supply_voltage_max", None)

        if result.get("error"):
            result["provider_status"] = PROVIDER_ERROR
            result["error"] = sanitize_provider_message(result.get("error"))
            diagnostic = log_supplier_diagnostic(
                request_id=resolved_request_id,
                supplier=str(source_name),
                stage="lookup",
                provider_status=PROVIDER_ERROR,
                error_message=result.get("error", ""),
            )
            attach_supplier_diagnostic(result, diagnostic)
            if started is not None:
                emit_timing(
                    "supplier.lookup",
                    duration_ms=round((_time.perf_counter() - started) * 1000.0, 1),
                    outcome="error",
                    provider=normalize_provider(source_name),
                    operation="lookup",
                )
            return result

        if (
            not str(result.get("manufacturer_part_number") or "").strip()
            or not _supplier_result_matches_request(source_name, part_number, result)
        ):
            result = _empty_supplier_result(
                source_name,
                provider_status=PROVIDER_PART_NOT_FOUND,
            )
            result.pop("error", None)
            diagnostic = log_supplier_diagnostic(
                request_id=resolved_request_id,
                supplier=str(source_name),
                stage="lookup",
                provider_status=PROVIDER_PART_NOT_FOUND,
            )
            attach_supplier_diagnostic(result, diagnostic)
            if started is not None:
                emit_timing(
                    "supplier.lookup",
                    duration_ms=round((_time.perf_counter() - started) * 1000.0, 1),
                    outcome="empty",
                    provider=normalize_provider(source_name),
                    operation="lookup",
                )
            return result

        # DigiKey brand constraint: reject a hit that does not match the
        # explicitly requested manufacturer (worker-thread safe).
        if requested_mfr and str(source_name or "") in {"DigiKey", "Mouser", "Newark", "Nexar Supply"}:
            result_mfr = str(result.get("manufacturer") or "").strip()
            brand_ok = False
            try:
                from apps.api.manufacturer_identity import manufacturers_match

                brand_ok = bool(
                    result_mfr
                    and manufacturers_match(
                        requested_mfr, result_mfr, mpn=part_number
                    )
                )
            except Exception:  # noqa: BLE001
                brand_ok = bool(
                    result_mfr
                    and result_mfr.casefold() == requested_mfr.casefold()
                )
            if not brand_ok:
                result = _empty_supplier_result(
                    source_name,
                    provider_status=PROVIDER_PART_NOT_FOUND,
                )
                result["identity_mismatch"] = {
                    "requested_manufacturer": requested_mfr,
                    "supplier_manufacturer": result_mfr,
                    "mpn": str(part_number or "").strip(),
                }
                result.pop("error", None)
                diagnostic = log_supplier_diagnostic(
                    request_id=resolved_request_id,
                    supplier=str(source_name),
                    stage="lookup",
                    provider_status=PROVIDER_PART_NOT_FOUND,
                    error_message=(
                        f"No {source_name} exact match for manufacturer {requested_mfr}"
                    ),
                )
                attach_supplier_diagnostic(result, diagnostic)
                if started is not None:
                    emit_timing(
                        "supplier.lookup",
                        duration_ms=round((_time.perf_counter() - started) * 1000.0, 1),
                        outcome="empty",
                        provider=normalize_provider(source_name),
                        operation="lookup",
                    )
                return result

     