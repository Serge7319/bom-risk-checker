from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st

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
from integrations.digikey_client import search_digikey_by_part_number
try:
    from integrations.digikey_client import (
        search_digikey_catalog_candidates,
        search_digikey_substitutions,
    )
except ImportError:
    def search_digikey_substitutions(part_number: str) -> list[dict]:
        return []

    def search_digikey_catalog_candidates(part_number: str) -> list[dict]:
        return []
from src.alternative_classification import merge_discovery_candidates, utc_now_iso
from src.secrets import get_secret
from src.part_images import normalize_supplier_image_url
from src.normalizer import normalize_part_number

try:
    from integrations.newark_client import search_newark_by_part_number
except ImportError as newark_import_error:
    _newark_import_error = newark_import_error

    def search_newark_by_part_number(part_number):
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
    """Try only case and separator formatting; never strip MPN suffixes."""
    raw = str(part_number or "").strip()
    variants = []
    for value in (raw, raw.upper(), normalize_part_number(raw)):
        candidate = str(value or "").strip()
        if candidate and candidate not in variants:
            variants.append(candidate)
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


def _safe_supplier_lookup(source_name, lookup_func, part_number, request_id: str = ""):
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
            candidate_result = lookup_func(query_variant)
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


def get_supplier_results(part_number, request_id: str = ""):
    from integrations.supplier_diagnostics import resolve_supplier_diagnostic_request_id

    resolved_request_id = resolve_supplier_diagnostic_request_id(request_id)
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


@st.cache_data(ttl=300, show_spinner=False)
def get_best_part_data(part_number: str) -> dict:
    from integrations.supplier_diagnostics import resolve_supplier_diagnostic_request_id

    # Resolve AF request_id via stack/last-id so Streamlit cache_data executions
    # still correlate diagnostics even when ContextVar is empty in this frame.
    # Tests may stub get_supplier_results with a one-arg callable — keep compatible.
    request_id = resolve_supplier_diagnostic_request_id()
    try:
        supplier_results = get_supplier_results(part_number, request_id=request_id)
    except TypeError:
        supplier_results = get_supplier_results(part_number)
    
    valid_results = sorted([
        result for result in supplier_results
        if result.get("provider_status") == PROVIDER_AVAILABLE
        and result.get("manufacturer_part_number")
    ], key=lambda result: str(result.get("source") or ""))

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
        return {
            "substitutions": "not_configured",
            "lookup": "not_configured",
            "message": f"{source_name} credentials are not configured.",
        }
    return {
        "substitutions": "not_supported",
        "lookup": "available",
        "message": f"{source_name} does not expose explicit substitute relationships.",
    }


def discover_alternative_candidates(part_number: str) -> dict:
    """Discover explicit substitutes and catalog candidates across configured sources."""
    requested = str(part_number or "").strip()
    retrieved_at = utc_now_iso()
    discovery = {
        "original_mpn": requested,
        "retrieved_at": retrieved_at,
        "providers": {},
        "explicit_count": 0,
        "catalog_count": 0,
        "provider_failures": [],
        "candidates": [],
        "has_incomplete_evidence": False,
    }
    if not requested:
        return discovery

    explicit_substitutes: list[dict] = []
    catalog_candidates: list[dict] = []

    digikey_status = {"substitutions": "ok", "catalog": "ok", "lookup": "available", "message": ""}
    try:
        if not _provider_configured("DIGIKEY_CLIENT_ID"):
            digikey_status = {
                "substitutions": "not_configured",
                "catalog": "not_configured",
                "lookup": "not_configured",
                "message": "DigiKey credentials are not configured.",
            }
            discovery["has_incomplete_evidence"] = True
        else:
            explicit_substitutes = search_digikey_substitutions(requested)
            catalog_candidates = search_digikey_catalog_candidates(requested)
            digikey_status["explicit_count"] = len(explicit_substitutes)
            digikey_status["catalog_count"] = len(catalog_candidates)
    except Exception as error:
        safe_message = sanitize_provider_message(error)
        digikey_status = {
            "substitutions": "error",
            "catalog": "error",
            "lookup": "error",
            "message": safe_message,
        }
        discovery["provider_failures"].append("DigiKey")
        discovery["has_incomplete_evidence"] = True
    discovery["providers"]["DigiKey"] = digikey_status

    for source_name in ("Mouser", "Newark"):
        status = _provider_discovery_status(source_name)
        discovery["providers"][source_name] = status
        if status.get("lookup") == "not_configured":
            discovery["has_incomplete_evidence"] = True

    merged = merge_discovery_candidates(
        explicit_substitutes,
        catalog_candidates,
        original_mpn=requested,
    )
    discovery["explicit_count"] = len(explicit_substitutes)
    discovery["catalog_count"] = len(catalog_candidates)
    discovery["candidates"] = merged
    return discovery


@st.cache_data(ttl=300, show_spinner=False)
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
