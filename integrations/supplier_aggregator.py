from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st

from integrations.stock_coercion import coerce_stock_total
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
from integrations.octopart_client import search_octopart_by_part_number
from src.alternative_classification import merge_discovery_candidates, utc_now_iso
from src.secrets import get_secret

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
        "stock_total": 0,
        "supplier_count": 0,
        "lead_time_weeks": None,
        "unit_price": 0.0,
        "has_alternates": False,
        "manufacturer": "",
        "description": "",
        "mouser_part_number": "",
        "manufacturer_part_number": "",
        "product_detail_url": "",
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


def _safe_supplier_lookup(source_name, lookup_func, part_number):
    from integrations.supplier_diagnostics import attach_supplier_diagnostic, log_supplier_diagnostic
    from src.performance_timing import (
        emit_timing,
        normalize_provider,
        supplier_outcome_from_status,
        timing_enabled,
    )
    import time as _time

    started = _time.perf_counter() if timing_enabled() else None
    try:
        if lookup_func is None:
            result = _empty_supplier_result(
                source_name,
                provider_status=PROVIDER_NOT_CONFIGURED,
                error=f"{source_name} is not configured",
            )
            diagnostic = log_supplier_diagnostic(
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

        result = lookup_func(part_number)

        if not result:
            result = _empty_supplier_result(
                source_name,
                provider_status=PROVIDER_ERROR,
                error=f"No response from {source_name}",
            )
            diagnostic = log_supplier_diagnostic(
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

        if not str(result.get("manufacturer_part_number") or "").strip():
            result["provider_status"] = PROVIDER_PART_NOT_FOUND
            result.pop("error", None)
            diagnostic = log_supplier_diagnostic(
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
        result["stock_total"] = coerce_stock_total(result.get("stock_total"))
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
            supplier=str(source_name),
            stage="lookup",
            provider_status=provider_status,
            error_message=safe_message,
            exception_type=type(error).__name__,
            error=error,
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


def _octopart_lookup_configured() -> bool:
    """Octopart requires both a client id and a client secret to be usable."""
    from integrations.supplier_diagnostics import _octopart_credentials_configured

    return _octopart_credentials_configured()


def _supplier_lookup_callable(source_name: str):
    """Return a lookup callable only when the distributor credentials are configured."""
    configured = {
        "Mouser": ("MOUSER_API_KEY", search_mouser_by_part_number),
        "DigiKey": ("DIGIKEY_CLIENT_ID", search_digikey_by_part_number),
        "Newark": ("NEWARK_API_KEY", search_newark_by_part_number),
        "Octopart": (
            ("NEXAR_CLIENT_ID", "OCTOPART_CLIENT_ID"),
            search_octopart_by_part_number,
        ),
    }
    entry = configured.get(source_name)
    if not entry:
        return None
    secret_names, lookup_func = entry
    if isinstance(secret_names, str):
        secret_names = (secret_names,)
    if source_name == "Octopart":
        return lookup_func if _octopart_lookup_configured() else None
    if any(_provider_configured(name) for name in secret_names):
        return lookup_func
    return None


def get_supplier_results(part_number):
    suppliers = [
        ("Mouser", _supplier_lookup_callable("Mouser")),
        ("DigiKey", _supplier_lookup_callable("DigiKey")),
        ("Newark", _supplier_lookup_callable("Newark")),
        ("Octopart", _supplier_lookup_callable("Octopart")),
    ]

    results = []

    with ThreadPoolExecutor(max_workers=len(suppliers)) as executor:
        future_to_supplier = {
            executor.submit(
                _safe_supplier_lookup,
                source_name,
                lookup_func,
                part_number,
            ): source_name
            for source_name, lookup_func in suppliers
        }

        for future in as_completed(future_to_supplier):
            results.append(future.result())

    return results


@st.cache_data(ttl=3600, show_spinner=False)
def get_best_part_data(part_number: str) -> dict:
    supplier_results = get_supplier_results(part_number)
    
    valid_results = [
        result for result in supplier_results
        if result.get("provider_status") == PROVIDER_AVAILABLE
        and result.get("manufacturer_part_number")
    ]

    if not valid_results:
        aggregated = default_aggregated_result(part_number, supplier_results)
        return aggregated

    best_result = max(
        valid_results,
        key=lambda result: coerce_stock_total(result.get("stock_total")),
    )

    total_market_stock = sum(
        coerce_stock_total(result.get("stock_total"))
        for result in valid_results
    )

    source_names = [
        result.get("source", "")
        for result in valid_results
        if result.get("source")
    ]

    best_result["supplier_count"] = len(valid_results)
    best_result["total_market_stock"] = total_market_stock
    best_result["stock_total"] = coerce_stock_total(best_result.get("stock_total"))
    best_result["sources_available"] = ", ".join(source_names)
    best_result["all_supplier_results"] = supplier_results
    provider_health = summarize_provider_health(supplier_results)
    best_result["provider_health"] = provider_health
    best_result["supplier_data_verified"] = provider_health["has_verified_data"]

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

    if not best_result.get("mounting_style"):
        for result in valid_results:
            if result.get("mounting_style"):
                best_result["mounting_style"] = result.get("mounting_style")
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
        "Octopart": ("NEXAR_CLIENT_ID", "OCTOPART_CLIENT_ID"),
    }
    if source_name == "Octopart":
        configured = _octopart_lookup_configured()
    else:
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

    for source_name in ("Mouser", "Newark", "Octopart"):
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
        "stock_total": 0,
        "supplier_count": 0,
        "lead_time_weeks": None,
        "unit_price": 0.0,
        "has_alternates": False,
        "product_detail_url": "",
        "package": "",
        "pin_count": 0,
        "mounting_style": "",
        "total_market_stock": 0,
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
