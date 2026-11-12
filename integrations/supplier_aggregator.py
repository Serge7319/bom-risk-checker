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
        if requested_mfr and str(source_name or "") == "DigiKey":
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
                result.pop("error", None)
                diagnostic = log_supplier_diagnostic(
                    request_id=resolved_request_id,
                    supplier=str(source_name),
                    stage="lookup",
                    provider_status=PROVIDER_PART_NOT_FOUND,
                    error_message=(
                        f"No DigiKey exact match for manufacturer {requested_mfr}"
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

        result["provider_status"] = PROVIDER_AVAILABLE
        result.pop("error", None)
        result["stock_total"] = parse_stock_total(result.get("stock_total"))
        if not str(result.get("retrieved_at") or "").strip():
            result["retrieved_at"] = utc_now_iso()
        if started is not None:
            emit_timing(
                "supplier.lookup",
                duration_ms=round((_time.perf_counter() - started) * 1000.0, 1),
                outcome=supplier_outcome_from_status(PROVIDER_AVAILABLE),
                provider=normalize_provider(source_name),
                operation="lookup",
            )
        return result

    except Exception as error:
        provider_status = classify_provider_exception(error)
        safe_message = sanitize_provider_message(error)
        diagnostic = log_supplier_diagnostic(
            request_id=resolved_request_id,
            supplier=str(source_name),
            stage="lookup",
            provider_status=provider_status,
            error_message=safe_message,
            exception_type=type(error).__name__,
            error=error,
            subreason=str(getattr(error, "subreason", "") or ""),
        )
        if started is not None:
            emit_timing(
                "supplier.lookup",
                duration_ms=round((_time.perf_counter() - started) * 1000.0, 1),
                outcome=supplier_outcome_from_status(provider_status),
                provider=normalize_provider(source_name),
                operation="lookup",
            )

        result = _empty_supplier_result(
            source_name,
            provider_status=provider_status,
            error=safe_message,
        )
        attach_supplier_diagnostic(result, diagnostic)
        return result


def _supplier_lookup_callable(source_name: str):
    """Return a lookup callable only when the distributor credentials are configured."""
    configured = {
        "Mouser": ("MOUSER_API_KEY", search_mouser_by_part_number),
        "DigiKey": ("DIGIKEY_CLIENT_ID", search_digikey_by_part_number),
        "Newark": ("NEWARK_API_KEY", search_newark_by_part_number),
    }
    entry = configured.get(source_name)
    if not entry:
        return None
    secret_names, lookup_func = entry
    if isinstance(secret_names, str):
        secret_names = (secret_names,)
    if any(_provider_configured(name) for name in secret_names):
        return lookup_func
    return None


def _legacy_mpn_review_leads(
    part_number: str,
    supplier_results: list[dict],
) -> list[dict]:
    """Search curated related order codes as leads, never as original-part evidence."""
    from integrations.legacy_mpn_routes import legacy_mpn_route

    route = legacy_mpn_route(part_number)
    if route is None:
        return []
    source_status = {
        str(row.get("source") or ""): str(row.get("provider_status") or "")
        for row in supplier_results
        if isinstance(row, dict)
    }
    tasks = []
    for candidate_mpn in route.get("query_mpns") or ():
        for source_name in ("Mouser", "DigiKey", "Newark"):
            if source_status.get(source_name) != PROVIDER_PART_NOT_FOUND:
                continue
            lookup = _supplier_lookup_callable(source_name)
            if lookup is not None:
                tasks.append((source_name, lookup, str(candidate_mpn)))
    if not tasks:
        return []

    def search_review_candidate(source_name, lookup, query_mpn):
        try:
            result = lookup(query_mpn)
        except Exception:
            return None
        if not isinstance(result, dict) or result.get("error"):
            return None
        returned_mpn = str(result.get("manufacturer_part_number") or "").strip()
        if not returned_mpn:
            return None
        if normalize_part_number(returned_mpn) != normalize_part_number(query_mpn):
            return None
        if normalize_part_number(returned_mpn) == normalize_part_number(part_number):
            return None
        return {
            "mpn": returned_mpn,
            "supplier": source_name,
            "manufacturer": str(result.get("manufacturer") or "").strip(),
            "product_url": str(result.get("product_detail_url") or "").strip(),
            "evidence_scope": "review_only_related_mpn",
            "retrieved_at": str(result.get("retrieved_at") or utc_now_iso()),
        }

    leads = []
    with ThreadPoolExecutor(max_workers=min(3, len(tasks))) as executor:
        futures = [
            executor.submit(search_review_candidate, source_name, lookup, query_mpn)
            for source_name, lookup, query_mpn in tasks
        ]
        for future in as_completed(futures):
            lead = future.result()
            if lead is not None:
                leads.append(lead)
    deduped = {}
    for lead in leads:
        key = (
            normalize_part_number(lead.get("mpn")),
            str(lead.get("supplier") or "").casefold(),
        )
        deduped[key] = lead
    return sorted(deduped.values(), key=lambda row: (row["mpn"], row["supplier"]))


def get_supplier_results(part_number, request_id: str = "", manufacturer: str = ""):
    from integrations.supplier_diagnostics import resolve_supplier_diagnostic_request_id

    resolved_request_id = resolve_supplier_diagnostic_request_id(request_id)
    requested_mfr = str(manufacturer or "").strip()
    suppliers = [
        ("Mouser", _supplier_lookup_callable("Mouser")),
        ("DigiKey", _supplier_lookup_callable("DigiKey")),
        ("Newark", _supplier_lookup_callable("Newark")),
    ]

    results = []

    with ThreadPoolExecutor(max_workers=len(suppliers)) as executor:
        future_to_supplier = {
            executor.submit(
                _safe_supplier_lookup,
                source_name,
                lookup_func,
                part_number,
                resolved_request_id,
                requested_mfr,
            ): source_name
            for source_name, lookup_func in suppliers
        }

        for future in as_completed(future_to_supplier):
            results.append(future.result())

    return results


def get_first_exact_supplier_result(part_number: str, request_id: str = "") -> dict:
    """Return the first exact-MPN supplier record that includes a datasheet.

    Review packets need only identity-safe source evidence. Waiting for every
    configured distributor made the review action wait for the slowest API,
    even after one supplier had already returned the requested part and its
    datasheet. Prefer that complete exact result as soon as it arrives. If no
    supplier provides a datasheet, return the best exact-MPN record after all
    suppliers finish so the caller can report that documentation is missing.
    """
    from integrations.supplier_diagnostics import (
        resolve_supplier_diagnostic_request_id,
    )

    requested = normalize_part_number(str(part_number or "").strip())
    if not requested:
        return {}

    resolved_request_id = resolve_supplier_diagnostic_request_id(request_id)
    suppliers = [
        ("Mouser", _supplier_lookup_callable("Mouser")),
        ("DigiKey", _supplier_lookup_callable("DigiKey")),
        ("Newark", _supplier_lookup_callable("Newark")),
    ]
    executor = ThreadPoolExecutor(max_workers=len(suppliers))
    futures = {
        executor.submit(
            _safe_supplier_lookup,
            source_name,
            lookup_func,
            part_number,
            resolved_request_id,
            "",
        ): source_name
        for source_name, lookup_func in suppliers
    }
    exact_results = []
    returned_early = False
    try:
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:
                continue
            if not isinstance(result, dict):
                continue
            if result.get("provider_status") != PROVIDER_AVAILABLE:
                continue
            returned_mpn = normalize_part_number(
                str(result.get("manufacturer_part_number") or "").strip()
            )
            if returned_mpn != requested:
                continue
            exact_results.append(result)
            datasheet_url = str(result.get("datasheet_url") or "").strip()
            if datasheet_url.startswith(("https://", "http://")):
                returned_early = True
                return result

        if exact_results:
            return max(
                exact_results,
                key=lambda result: bool(
                    str(result.get("product_detail_url") or "").startswith(
                        ("https://", "http://")
                    )
                ),
            )
        return {}
    finally:
        # Running distributor requests have bounded HTTP timeouts. Do not keep
        # the Streamlit interaction blocked after an exact datasheet is ready.
        executor.shutdown(wait=not returned_early, cancel_futures=returned_early)


@cache_data(ttl=300, show_spinner=False)
def get_best_part_data(part_number: str, manufacturer: str = "") -> dict:
    from integrations.supplier_diagnostics import resolve_supplier_diagnostic_request_id

    # Resolve AF request_id via stack/last-id so Streamlit cache_data executions
    # still correlate diagnostics even when ContextVar is empty in this frame.
    # Tests may stub get_supplier_results with a one-arg callable — keep compatible.
    request_id = resolve_supplier_diagnostic_request_id()
    requested_mfr = str(manufacturer or "").strip()
    try:
        supplier_results = get_supplier_results(
            part_number, request_id=request_id, manufacturer=requested_mfr
        )
    except TypeError:
        try:
            supplier_results = get_supplier_results(part_number, request_id=request_id)
        except TypeError:
            supplier_results = get_supplier_results(part_number)

    valid_results = sorted([
        result for result in supplier_results
        if result.get("provider_status") == PROVIDER_AVAILABLE
        and result.get("manufacturer_part_number")
    ], key=lambda result: str(result.get("source") or ""))

    # When a brand was requested, never aggregate a different manufacturer's hit
    # as the verified original identity.
    if requested_mfr and valid_results:
        try:
            from apps.api.manufacturer_identity import manufacturers_match
        except Exception:  # noqa: BLE001
            manufacturers_match = None  # type: ignore[assignment]
        matched = []
        for row in valid_results:
            row_mfr = str(row.get("manufacturer") or "").strip()
            if not row_mfr:
                continue
            if manufacturers_match and manufacturers_match(
                requested_mfr, row_mfr, mpn=part_number
            ):
                matched.append(row)
            elif (
                not manufacturers_match
                and row_mfr.casefold() == requested_mfr.casefold()
            ):
                matched.append(row)
        valid_results = matched

    if not valid_results:
        aggregated = default_aggregated_result(part_number, supplier_results)
        aggregated["supplier_offers"] = []
        from integrations.legacy_mpn_routes import legacy_mpn_route, legacy_route_status

        route = legacy_mpn_route(part_number)
        if route is not None:
            # Only attribute distributor metrics through a narrow list of
            # manufacturer-documented orderable codes. Family-level searches
            # and unverified near matches remain review leads, never scored
            # evidence. The candidate lookup itself enforces an exact MPN
            # match before returning any supplier metrics.
            order_code_search_attempted = False
            for order_code in route.get("assessment_order_codes") or ():
                if not isinstance(order_code, dict):
                    continue
                candidate_mpn = str(order_code.get("mpn") or "").strip()
                if not candidate_mpn:
                    continue
                try:
                    candidate_data = get_best_part_data(candidate_mpn)
                except Exception:
                    candidate_data = {}
                if not isinstance(candidate_data, dict):
                    candidate_data = {}
                candidate_health = candidate_data.get("provider_health") or {}
                if not isinstance(candidate_health, dict):
                    candidate_health = {}
                try:
                    order_code_search_attempted = order_code_search_attempted or int(
                        candidate_health.get("configured_count") or 0
                    ) > 0
                except (TypeError, ValueError):
                    pass
                returned_mpn = str(
                    candidate_data.get("manufacturer_part_number") or ""
                ).strip()
                if (
                    not candidate_data.get("supplier_data_verified")
                    or normalize_part_number(returned_mpn)
                    != normalize_part_number(candidate_mpn)
                ):
                    continue

                mapped = dict(candidate_data)
                mapped["mpn"] = str(part_number or "").strip()
                mapped["searched_part_number"] = str(part_number or "").strip()
                mapped["requested_mpn"] = str(part_number or "").strip()
                mapped["assessment_basis"] = "manufacturer_documented_order_code"
                mapped["assessment_evidence_mpn"] = returned_mpn
                mapped["assessment_basis_note"] = (
                    f"Risk evidence is from manufacturer-listed order code {returned_mpn} "
                    f"for BOM part {str(part_number or '').strip()}. Verify the installed "
                    "device/package and ordering code before procurement release."
                )
                identity_source = str(order_code.get("source_url") or "").strip()
                mapped["alternate_search_status"] = (
                    f"Manufacturer-listed order code matched: {returned_mpn}. "
                    f"{str(order_code.get('basis') or '').strip()} Live distributor values "
                    "are for this exact order code; confirm the BOM package and ordering "
                    "suffix before release."
                    + (f" Manufacturer reference: {identity_source}" if identity_source else "")
                )
                mapped["legacy_mpn_review_leads"] = [{
                    "mpn": returned_mpn,
                    "supplier": str(mapped.get("source") or ""),
                    "manufacturer": str(order_code.get("manufacturer") or ""),
                    "product_url": str(mapped.get("product_detail_url") or ""),
                    "evidence_scope": "manufacturer_documented_order_code",
                    "retrieved_at": str(mapped.get("retrieved_at") or utc_now_iso()),
                }]
                return mapped

            searched = any(
                str(row.get("provider_status") or "") == PROVIDER_PART_NOT_FOUND
                for row in supplier_results
                if isinstance(row, dict)
            )
            # A family-level route is still discovery-only. For recognized
            # order-code mappings, the exact candidate lookup above already
            # queried the listed codes; avoid a duplicate second API request.
            leads = (
                _legacy_mpn_review_leads(part_number, supplier_results)
                if searched and not route.get("assessment_order_codes")
                else []
            )
            aggregated["legacy_mpn_review_leads"] = leads
            aggregated["alternate_search_status"] = legacy_route_status(
                part_number,
                leads,
                searched=searched or order_code_search_attempted,
            )
        return aggregated

    stock_by_result = {
        id(result): parse_stock_total(result.get("stock_total"))
        for result in valid_results
    }
    stock_known_results = [
        result for result in valid_results if stock_by_result[id(result)] is not None
    ]
    selected_result = max(
        valid_results,
        key=lambda result: (
            stock_by_result[id(result)] is not None,
            stock_by_result[id(result)] if stock_by_result[id(result)] is not None else -1,
            str(result.get("source") or ""),
        ),
    )
    best_result = dict(selected_result)

    total_market_stock = (
        sum(int(stock_by_result[id(result)]) for result in stock_known_results)
        if stock_known_results else None
    )

    source_names = sorted({
        result.get("source", "")
        for result in valid_results
        if result.get("source")
    })

    best_result["supplier_count"] = len(valid_results)
    best_result["total_market_stock"] = total_market_stock
    best_result["stock_total"] = stock_by_result[id(selected_result)]
    best_result["sources_available"] = ", ".join(source_names)
    best_result["all_supplier_results"] = supplier_results
    provider_health = summarize_provider_health(supplier_results)
    best_result["provider_health"] = provider_health
    best_result["supplier_data_verified"] = provider_health["has_verified_data"]
    best_result["stock_data_sources"] = sorted({
        str(result.get("source") or "") for result in stock_known_results
        if result.get("source")
    })
    best_result["stock_data_complete"] = len(stock_known_results) == len(valid_results)
    lifecycle_status, lifecycle_evidence, lifecycle_conflict = _resolve_lifecycle(valid_results)
    best_result["lifecycle_status"] = lifecycle_status
    best_result["lifecycle_evidence"] = lifecycle_evidence
    best_result["lifecycle_conflict"] = lifecycle_conflict

    lead_time_rows = [
        result for result in sorted(valid_results, key=lambda row: str(row.get("source") or ""))
        if result.get("lead_time_weeks") not in (None, "")
    ]
    best_result["lead_time_evidence"] = [
        {
            "source": str(result.get("source") or "Supplier"),
            "weeks": result.get("lead_time_weeks"),
            "retrieved_at": result.get("retrieved_at"),
        }
        for result in lead_time_rows
    ]
    if best_result.get("lead_time_weeks") in (None, "") and lead_time_rows:
        best_result["lead_time_weeks"] = lead_time_rows[0].get("lead_time_weeks")
        best_result["lead_time_source"] = lead_time_rows[0].get("source")
    elif best_result.get("lead_time_weeks") not in (None, ""):
        best_result["lead_time_source"] = best_result.get("source")

    # Borrow missing package / pin-count / mounting-style data
    # from any other supplier that has it.
    if not best_result.get("package"):
        for result in valid_results:
            if result.get("package"):
                best_result["package"] = result.get("package")
                break

    if not best_result.get("pin_count"):
        for result in valid_results:
            if result.get("pin_count"):
                best_result["pin_count"] = result.get("pin_count")
                break

    best_result["pin_count"] = sanitize_stored_pin_count(
        best_result.get("pin_count"),
        package_text=best_result.get("package", ""),
    )

    if not best_result.get("mounting_style"):
        for result in valid_results:
            if result.get("mounting_style"):
                best_result["mounting_style"] = result.get("mounting_style")
                break

    if not best_result.get("image_url"):
        for result in valid_results:
            image_url = normalize_supplier_image_url(
                result.get("image_url"), provider=result.get("source", "")
            )
            if image_url:
                best_result["image_url"] = image_url
                break

    if not best_result.get("datasheet_url"):
        for result in valid_results:
            if result.get("datasheet_url"):
                best_result["datasheet_url"] = result.get("datasheet_url")
                break

    if not best_result.get("voltage_range"):
        for result in valid_results:
            if result.get("voltage_range"):
                best_result["voltage_range"] = result.get("voltage_range")
                break

    if best_result.get("supply_voltage_min") is None:
        for result in valid_results:
            if result.get("supply_voltage_min") is not None:
                best_result["supply_voltage_min"] = result.get("supply_voltage_min")
                break

    if best_result.get("supply_voltage_max") is None:
        for result in valid_results:
            if result.get("supply_voltage_max") is not None:
                best_result["supply_voltage_max"] = result.get("supply_voltage_max")
                break

    if not best_result.get("architecture"):
        for result in valid_results:
            if result.get("architecture"):
                best_result["architecture"] = result.get("architecture")
                break

    if not best_result.get("channel_count"):
        for result in valid_results:
            if result.get("channel_count"):
                best_result["channel_count"] = result.get("channel_count")
                break

    if best_result.get("bandwidth_mhz") is None:
        for result in valid_results:
            if result.get("bandwidth_mhz") is not None:
                best_result["bandwidth_mhz"] = result.get("bandwidth_mhz")
                break

    if best_result.get("slew_rate_v_us") is None:
        for result in valid_results:
            if result.get("slew_rate_v_us") is not None:
                best_result["slew_rate_v_us"] = result.get("slew_rate_v_us")
                break

    if best_result.get("input_offset_mv") is None:
        for result in valid_results:
            if result.get("input_offset_mv") is not None:
                best_result["input_offset_mv"] = result.get("input_offset_mv")
                break

    if best_result.get("quiescent_current_ma") is None:
        for result in valid_results:
            if result.get("quiescent_current_ma") is not None:
                best_result["quiescent_current_ma"] = result.get("quiescent_current_ma")
                break

    if best_result.get("input_bias_na") is None:
        for result in valid_results:
            if result.get("input_bias_na") is not None:
                best_result["input_bias_na"] = result.get("input_bias_na")
                break

    # Passive-component specifications must survive supplier selection. The
    # highest-stock supplier often has less parametric data than DigiKey; copy
    # verified values instead of presenting them as unavailable downstream.
    from src.component_family_profiles import all_parametric_keys

    for field_name in all_parametric_keys(include_common=False):
        if not best_result.get(field_name):
            for result in valid_results:
                if result.get(field_name):
                    best_result[field_name] = result.get(field_name)
                    break

    for field_name in (
        "capacitance", "resistance", "inductance", "tolerance", "rated_voltage",
        "dielectric", "power_rating", "temperature_coefficient", "esr", "dcr",
        "rated_current", "saturation_current",
    ):
        if not best_result.get(field_name):
            for result in valid_results:
                if result.get(field_name):
                    best_result[field_name] = result.get(field_name)
                    break

    if best_result.get("gbw_mhz") is None:
        for result in valid_results:
            if result.get("gbw_mhz") is not None:
                best_result["gbw_mhz"] = result.get("gbw_mhz")
                break

    best_result.setdefault("package", "")
    best_result.setdefault("pin_count", 0)
    best_result.setdefault("mounting_style", "")
    best_result.setdefault("datasheet_url", "")
    best_result.setdefault("voltage_range", "")
    best_result.setdefault("architecture", "")
    best_result.setdefault("channel_count", 0)
    best_result.setdefault("supply_voltage_min", None)
    best_result.setdefault("supply_voltage_max", None)
    best_result.setdefault("bandwidth_mhz", None)
    best_result.setdefault("slew_rate_v_us", None)
    best_result.setdefault("input_offset_mv", None)
    best_result.setdefault("quiescent_current_ma", None)
    best_result.setdefault("input_bias_na", None)
    best_result.setdefault("gbw_mhz", None)
    from src.saved_bom_cost import collect_supplier_offers

    best_result["supplier_offers"] = collect_supplier_offers(
        valid_results,
        mpn=str(best_result.get("manufacturer_part_number") or part_number),
    )
    for field_name in (
        "capacitance",
        "resistance",
        "inductance",
        "tolerance",
        "rated_voltage",
        "dielectric",
        "power_rating",
        "temperature_coefficient",
        "esr",
        "dcr",
        "rated_current",
        "saturation_current",
        "device_type",
        "reverse_voltage",
        "forward_current",
    ):
        best_result.setdefault(field_name, "")

    return best_result


def _provider_configured(secret_name: str) -> bool:
    try:
        return bool(str(get_secret(secret_name, required=False) or "").strip())
    except Exception:
        return False


def _provider_discovery_status(source_name: str) -> dict:
    secret_map = {
        "DigiKey": ("DIGIKEY_CLIENT_ID",),
        "Mouser": ("MOUSER_API_KEY",),
        "Newark": ("NEWARK_API_KEY",),
    }
    secret_names = secret_map.get(source_name, ())
    configured = bool(secret_names) and any(
        _provider_configured(name) for name in secret_names
    )
    if not configured:
        is_relationship_provider = source_name == "DigiKey"
        return {
            "substitutions": "not_configured" if is_relationship_provider else "not_supported",
            "catalog": "not_configured",
            "family_search": "not_configured",
            "parametric_search": "not_configured" if is_relationship_provider else "not_requested",
            "lookup": "not_configured",
            "message": f"{source_name} credentials are not configured.",
        }
    return {
        "substitutions": "not_supported",
        "catalog": "available",
        "family_search": "available",
        "lookup": "available",
        "message": "Catalog results are discovery leads, not confirmed substitutes.",
    }


def _parametric_catalog_search_terms(source_part: dict | None) -> list[str]:
    """Build a conservative distributor query from verified source attributes."""
    part = source_part if isinstance(source_part, dict) else {}
    from src.datasheet_comparison import infer_component_family

    family = infer_component_family(part)
    family_fields = {
        "Capacitor": ("capacitance", "rated_voltage", "dielectric", "package"),
        "Resistor": ("resistance", "tolerance", "power_rating", "package"),
        "Inductor": ("inductance", "rated_current", "saturation_current", "package"),
    }
    keys = family_fields.get(family, ())
    values: list[str] = []
    for key in keys:
        value = str(part.get(key) or "").strip()
        if not value:
            continue
        value = (
            value.replace("µ", "u")
            .replace("μ", "u")
            .replace("±", "")
            .replace("Ω", "ohm")
            .replace("Ω", "ohm")
        )
        if key == "package":
            value = value.split()[0]
        value = re.sub(
            r"(?<=\d)\s+(?=(?:uF|mF|nF|pF|V|A|W|ohm|uH|mH|nH)\b)",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = " ".join(value.split())
        if value and value.casefold() not in {item.casefold() for item in values}:
            values.append(value)
    if len(values) < 2:
        return []
    family_query = {
        "Capacitor": "ceramic capacitor",
        "Resistor": "resistor",
        "Inductor": "inductor",
    }[family]
    return [" ".join((*values, family_query))]


def discover_alternative_candidates(
    part_number: str,
    *,
    include_family_search: bool = True,
    original_data: dict | None = None,
    manufacturer: str = "",
) -> dict:
    """Discover explicit substitutes and catalog candidates across configured sources.

    When ``manufacturer`` is provided, drop catalog/explicit rows whose supplier
    manufacturer clearly conflicts with the requested brand (including exact-MPN
    lineage aliases). Rows with a blank manufacturer stay as needs-verification leads.
    """
    requested = str(part_number or "").strip()
    requested_mfr = str(manufacturer or "").strip()
    retrieved_at = utc_now_iso()
    discovery = {
        "original_mpn": requested,
        "retrieved_at": retrieved_at,
        "requested_manufacturer": requested_mfr,
        "providers": {},
        "explicit_count": 0,
        "explicit_raw_count": 0,
        "explicit_retained_count": 0,
        "catalog_count": 0,
        "catalog_raw_count": 0,
        "catalog_retained_count": 0,
        "manufacturer_filtered_count": 0,
        "catalog_filter_summary": "",
        "provider_failures": [],
        "candidates": [],
        "has_incomplete_evidence": False,
    }
    if not requested:
        return discovery

    explicit_substitutes: list[dict] = []
    catalog_candidates: list[dict] = []
    # Punctuation variants + curated legacy family bases expand discovery only.
    # Exact identity still requires normalize_part_number equality elsewhere.
    query_variants = list(_supplier_query_variants(requested))
    try:
        from integrations.legacy_mpn_routes import legacy_mpn_route

        route = legacy_mpn_route(requested)
        if route is not None:
            for family_mpn in route.get("query_mpns") or ():
                candidate = str(family_mpn or "").strip()
                if candidate and candidate not in query_variants:
                    query_variants.append(candidate)
    except Exception:
        pass
    primary_query = query_variants[0] if query_variants else requested
    extra_family_terms = [
        term for term in query_variants[1:]
        if term and term.casefold() != primary_query.casefold()
    ]

    def _search_digikey() -> tuple[str, dict, list[dict], list[dict], Exception | None]:
        status = {
            "substitutions": "available",
            "catalog": "available",
            "family_search": "ok" if include_family_search else "not_requested",
            "parametric_search": "not_requested",
            "lookup": "available",
            "message": "",
        }
        if not _provider_configured("DIGIKEY_CLIENT_ID"):
            status.update({
                "substitutions": "not_configured",
                "catalog": "not_configured",
                "family_search": "not_configured",
                "parametric_search": "not_configured",
                "lookup": "not_configured",
                "message": "DigiKey credentials are not configured.",
            })
            return "DigiKey", status, [], [], None
        explicit: list[dict] = []
        catalog: list[dict] = []
        errors: list[str] = []
        try:
            explicit = search_digikey_substitutions(primary_query)
            status["substitutions"] = "ok"
        except Exception as error:
            status["substitutions"] = "error"
            errors.append(sanitize_provider_message(error))
        try:
            parametric_terms = _parametric_catalog_search_terms(original_data)
            additional = list(dict.fromkeys([*(parametric_terms or []), *extra_family_terms]))
            catalog = search_digikey_catalog_candidates(
                primary_query,
                include_family_search=include_family_search,
                additional_search_terms=additional or None,
            )
            status["catalog"] = "ok"
            status["parametric_search"] = "ok" if parametric_terms else "not_requested"
            status["parametric_count"] = sum(
                1 for row in catalog
                if isinstance(row, dict)
                and str(row.get("discovery_scope") or "").casefold() == "parametric_search"
            )
        except Exception as error:
            status["catalog"] = "error"
            status["parametric_search"] = "error" if original_data else "not_requested"
            if include_family_search:
                status["family_search"] = "error"
            errors.append(sanitize_provider_message(error))
        if errors:
            status["message"] = " ".join(dict.fromkeys(errors))
        status["explicit_count"] = len(explicit)
        status["explicit_raw_count"] = len(explicit)
        status["explicit_retained_count"] = len(explicit)
        status["catalog_count"] = len(catalog)
        status["catalog_raw_count"] = len(catalog)
        status["catalog_retained_count"] = len(catalog)
        # Uniform shape: (source, status, primary_rows, secondary_rows, error)
        return "DigiKey", status, explicit, catalog, None

    def _search_catalog_provider(
        source_name: str, search_func
    ) -> tuple[str, dict, list[dict], list[dict], Exception | None]:
        from integrations.newark_client import NewarkCatalogPartialResultsError

        status = _provider_discovery_status(source_name)
        # Unconfigured: report configuration accurately and skip catalog requests.
        if status.get("lookup") == "not_configured":
            return source_name, status, [], [], None
        try:
            candidates = search_func(
                requested,
                include_family_search=include_family_search,
            )
            status.update({
                "catalog": "ok",
                "family_search": "ok" if include_family_search else "not_requested",
                "catalog_count": len(candidates),
                "catalog_raw_count": len(candidates),
                "catalog_retained_count": len(candidates),
                "message": "Catalog results are discovery leads, not confirmed substitutes.",
            })
            return source_name, status, candidates, [], None
        except NewarkCatalogPartialResultsError as error:
            cause = error.cause if isinstance(getattr(error, "cause", None), Exception) else error
            provider_status = classify_provider_exception(cause)
            safe_message = sanitize_provider_message(cause)
            partial_rows = list(error.candidates or [])
            status.update({
                "catalog": "partial",
                "family_search": "error" if include_family_search else "not_requested",
                "lookup": "available",
                "catalog_count": len(partial_rows),
                "catalog_raw_count": len(partial_rows),
                "catalog_retained_count": len(partial_rows),
                "message": safe_message,
                "provider_status": provider_status,
                "exception_type": type(cause).__name__,
                "failure_subreason": str(
                    getattr(cause, "subreason", "")
                    or getattr(error, "subreason", "")
                    or ""
                ),
                "failed_term": str(getattr(error, "failed_term", "") or ""),
                "partial_candidates": True,
            })
            return source_name, status, partial_rows, [], cause
        except Exception as error:
            provider_status = classify_provider_exception(error)
            safe_message = sanitize_provider_message(error)
            status.update({
                "catalog": "error",
                "family_search": "error" if include_family_search else "not_requested",
                "lookup": "error",
                "message": safe_message,
                "provider_status": provider_status,
                "exception_type": type(error).__name__,
                "failure_subreason": str(getattr(error, "subreason", "") or ""),
            })
            return source_name, status, [], [], error

    from integrations.supplier_diagnostics import (
        log_supplier_diagnostic,
        resolve_supplier_diagnostic_request_id,
    )

    discovery_request_id = resolve_supplier_diagnostic_request_id()
    catalog_failures: list[tuple[str, dict, Exception | None]] = []
    catalog_zero_results: list[str] = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_search_digikey): "DigiKey",
            executor.submit(_search_catalog_provider, "Mouser", search_mouser_catalog_candidates): "Mouser",
            executor.submit(_search_catalog_provider, "Newark", search_newark_catalog_candidates): "Newark",
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as error:
                safe_message = sanitize_provider_message(error)
                # A provider failure is partial coverage; it never means that
                # no compatible or market alternatives exist.
                source_name = futures[future]
                status = {
                    "substitutions": "error",
                    "catalog": "error",
                    "family_search": "error" if include_family_search else "not_requested",
                    "parametric_search": "error" if original_data else "not_requested",
                    "lookup": "error",
                    "message": safe_message,
                    "provider_status": classify_provider_exception(error),
                    "exception_type": type(error).__name__,
                    "failure_subreason": str(getattr(error, "subreason", "") or ""),
                }
                result = (source_name, status, [], [], error)
            source_name, status, primary_rows, secondary_rows, failure_exc = result
            discovery["providers"][source_name] = status
            if source_name == "DigiKey":
                explicit_substitutes.extend(primary_rows)
                catalog_candidates.extend(secondary_rows)
            else:
                catalog_candidates.extend(primary_rows)

            catalog_state = str(status.get("catalog") or "").strip().casefold()
            lookup_state = str(status.get("lookup") or "").strip().casefold()
            if lookup_state == "not_configured" or catalog_state == "not_configured":
                # Configuration gap only — never treat as an upstream catalog failure.
                discovery["has_incomplete_evidence"] = True
                continue

            if (
                lookup_state == "error"
                or catalog_state in {"error", "partial"}
                or str(status.get("substitutions") or "").strip().casefold() == "error"
            ):
                discovery["has_incomplete_evidence"] = True
                if (
                    lookup_state == "error"
                    or catalog_state in {"error", "partial"}
                    or str(status.get("substitutions") or "").strip().casefold() == "error"
                ):
                    if source_name not in discovery["provider_failures"]:
                        discovery["provider_failures"].append(source_name)
                    if catalog_state in {"error", "partial"} and failure_exc is not None:
                        catalog_failures.append((source_name, status, failure_exc))
                    elif catalog_state == "error":
                        catalog_failures.append((source_name, status, failure_exc))
            elif (
                source_name in {"Mouser", "Newark"}
                and catalog_state == "ok"
                and int(status.get("catalog_count") or 0) == 0
            ):
                # Defer zero-result diagnostics until merged candidates are known.
                catalog_zero_results.append(source_name)

    from src.alternative_classification import normalize_mpn_for_comparison

    def _tag_channel(rows: list[dict], channel: str) -> list[dict]:
        tagged: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            payload = dict(row)
            payload["discovery_channel"] = channel
            tagged.append(payload)
        return tagged

    def _count_by_source(rows: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            source = str(row.get("source") or row.get("Supplier") or "").strip()
            if not source:
                continue
            counts[source] = counts.get(source, 0) + 1
        return counts

    def _unique_channel_count(rows: list[dict], channel: str) -> int:
        keys: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("discovery_channel") or "").casefold() != channel:
                continue
            key = normalize_mpn_for_comparison(
                str(row.get("manufacturer_part_number") or "")
            )
            if key:
                keys.add(key)
        return len(keys)

    catalog_raw_total = 0
    explicit_raw_total = 0
    for status in discovery["providers"].values():
        if not isinstance(status, dict):
            continue
        try:
            raw_catalog = int(
                status.get("catalog_raw_count")
                if status.get("catalog_raw_count") is not None
                else status.get("catalog_count")
                or 0
            )
        except (TypeError, ValueError):
            raw_catalog = 0
        try:
            raw_explicit = int(
                status.get("explicit_raw_count")
                if status.get("explicit_raw_count") is not None
                else status.get("explicit_count")
                or 0
            )
        except (TypeError, ValueError):
            raw_explicit = 0
        status["catalog_raw_count"] = max(0, raw_catalog)
        status["explicit_raw_count"] = max(0, raw_explicit)
        catalog_raw_total += max(0, raw_catalog)
        explicit_raw_total += max(0, raw_explicit)
    discovery["catalog_raw_count"] = catalog_raw_total
    discovery["explicit_raw_count"] = explicit_raw_total

    explicit_substitutes = _tag_channel(explicit_substitutes, "explicit")
    catalog_candidates = _tag_channel(catalog_candidates, "catalog")

    manufacturer_filtered_catalog = 0
    if requested_mfr:
        try:
            from apps.api.manufacturer_identity import manufacturers_match
        except Exception:  # noqa: BLE001
            manufacturers_match = None  # type: ignore[assignment]

        def _brand_allowed(row: dict) -> bool:
            row_mfr = str(row.get("manufacturer") or "").strip()
            if not row_mfr:
                return True
            if manufacturers_match:
                return bool(
                    manufacturers_match(requested_mfr, row_mfr, mpn=requested)
                )
            return row_mfr.casefold() == requested_mfr.casefold()

        before_catalog = len(catalog_candidates)
        before_explicit = len(explicit_substitutes)
        explicit_substitutes = [row for row in explicit_substitutes if _brand_allowed(row)]
        catalog_candidates = [row for row in catalog_candidates if _brand_allowed(row)]
        manufacturer_filtered_catalog = max(0, before_catalog - len(catalog_candidates))
        manufacturer_filtered_explicit = max(
            0, before_explicit - len(explicit_substitutes)
        )
        if manufacturer_filtered_catalog or manufacturer_filtered_explicit:
            discovery["has_incomplete_evidence"] = True
            discovery["manufacturer_filter_applied"] = True
        # Catalog-only count for filter summaries (explicit tracked separately).
        discovery["manufacturer_filtered_count"] = manufacturer_filtered_catalog
        discovery["manufacturer_filtered_explicit_count"] = (
            manufacturer_filtered_explicit
        )

    # Per-provider retained after manufacturer/lineage filter (pre-dedup),
    # catalog channel only — never mix in explicit substitutions.
    catalog_retained_by_source = _count_by_source(catalog_candidates)
    explicit_retained_by_source = _count_by_source(explicit_substitutes)
    for source_name, status in discovery["providers"].items():
        if not isinstance(status, dict):
            continue
        status["catalog_retained_count"] = int(
            catalog_retained_by_source.get(source_name, 0)
        )
        if "explicit_raw_count" in status or "explicit_count" in status:
            status["explicit_retained_count"] = int(
                explicit_retained_by_source.get(source_name, 0)
            )

    merged = merge_discovery_candidates(
        explicit_substitutes,
        catalog_candidates,
        original_mpn=requested,
    )
    catalog_retained = _unique_channel_count(merged, "catalog")
    explicit_retained = _unique_channel_count(merged, "explicit")
    # Refresh per-provider retained from unique post-dedup merged rows.
    catalog_merged_by_source: dict[str, set[str]] = {}
    explicit_merged_by_source: dict[str, set[str]] = {}
    for row in merged:
        if not isinstance(row, dict):
            continue
        channel = str(row.get("discovery_channel") or "").casefold()
        source = str(row.get("source") or row.get("Supplier") or "").strip()
        key = normalize_mpn_for_comparison(
            str(row.get("manufacturer_part_number") or "")
        )
        if not source or not key:
            continue
        bucket = (
            catalog_merged_by_source
            if channel == "catalog"
            else explicit_merged_by_source if channel == "explicit" else None
        )
        if bucket is None:
            continue
        bucket.setdefault(source, set()).add(key)
    for source_name, status in discovery["providers"].items():
        if not isinstance(status, dict):
            continue
        status["catalog_retained_count"] = len(
            catalog_merged_by_source.get(source_name, set())
        )
        if "explicit_raw_count" in status or "explicit_count" in status:
            status["explicit_retained_count"] = len(
                explicit_merged_by_source.get(source_name, set())
            )

    discovery["explicit_count"] = len(explicit_substitutes)
    discovery["explicit_retained_count"] = explicit_retained
    discovery["catalog_count"] = len(catalog_candidates)
    discovery["catalog_retained_count"] = catalog_retained
    discovery["candidates"] = merged
    filter_bits: list[str] = []
    if manufacturer_filtered_catalog:
        filter_bits.append(
            f"{manufacturer_filtered_catalog} catalog leads removed by "
            "manufacturer/lineage filter"
        )
    catalog_dedup_removed = max(0, len(catalog_candidates) - catalog_retained)
    if catalog_dedup_removed:
        filter_bits.append(
            f"{catalog_dedup_removed} catalog leads removed by deduplication"
        )
    if catalog_raw_total and catalog_retained < catalog_raw_total:
        filter_bits.append(
            f"{catalog_raw_total} raw catalog matches → {catalog_retained} retained"
        )
    discovery["catalog_filter_summary"] = "; ".join(dict.fromkeys(filter_bits))

    # Emit correlated catalog-search diagnostics only after all suppliers settle.
    retained = bool(merged)
    for source_name in catalog_zero_results:
        log_supplier_diagnostic(
            request_id=discovery_request_id,
            supplier=source_name,
            stage="catalog_search",
            provider_status=PROVIDER_PART_NOT_FOUND,
            subreason="zero_results",
            retained_candidates=retained,
        )
    for source_name, status, failure_exc in catalog_failures:
        provider_status = str(
            status.get("provider_status")
            or (
                classify_provider_exception(failure_exc)
                if failure_exc is not None
                else PROVIDER_ERROR
            )
        )
        log_supplier_diagnostic(
            request_id=discovery_request_id,
            supplier=source_name,
            stage="catalog_search",
            provider_status=provider_status,
            error_message=str(status.get("message") or ""),
            exception_type=str(
                status.get("exception_type")
                or (type(failure_exc).__name__ if failure_exc is not None else "")
            ),
            error=failure_exc,
            subreason=str(status.get("failure_subreason") or ""),
            retained_candidates=retained,
        )
    return discovery


@cache_data(ttl=300, show_spinner=False)
def search_supplier_alternatives(part_number: str) -> list[dict]:
    """Return ranked supplier evidence without treating catalog matches as direct substitutes.

    Never stop discovery after the first distributor relationship. A valid
    direct substitute may coexist with catalog/family candidates that reveal
    ordering-code variants the substitutions endpoint did not return.
    """
    discovery = discover_alternative_candidates(part_number)
    return list(discovery.get("candidates") or [])


def default_aggregated_result(part_number: str, supplier_results: list) -> dict:
    provider_health = summarize_provider_health(supplier_results)
    return {
        "source": "No supplier match",
        "searched_part_number": part_number,
        "mpn": part_number,
        "manufacturer_part_number": part_number,
        "manufacturer": "",
        "description": "",
        "lifecycle_status": "Unknown",
        "stock_total": None,
        "supplier_count": None,
        "lead_time_weeks": None,
        "unit_price": 0.0,
        "has_alternates": False,
        "product_detail_url": "",
        "package": "",
        "pin_count": 0,
        "mounting_style": "",
        "total_market_stock": None,
        "stock_data_sources": [],
        "stock_data_complete": False,
        "lifecycle_evidence": [],
        "lifecycle_conflict": False,
        "lead_time_evidence": [],
        "sources_available": "",
        "all_supplier_results": supplier_results,
        "provider_health": provider_health,
        "supplier_data_verified": provider_health["has_verified_data"],
        "voltage_range": "",
        "architecture": "",
        "channel_count": 0,
        "supply_voltage_min": None,
        "supply_voltage_max": None,
        "bandwidth_mhz": None,
        "slew_rate_v_us": None,
    }
