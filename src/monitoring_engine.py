import json
import logging
import math
import re

from src.saved_bom_cost import json_safe_value


_logger = logging.getLogger(__name__)


def _optional_number(value):
    """Convert a numeric snapshot value to a finite float or None."""
    value = json_safe_value(value)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _optional_integer(value):
    """Convert a whole-number snapshot count to an integer or None."""
    number = _optional_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _display_text(value, default=""):
    value = json_safe_value(value)
    if value is None:
        return default
    text = str(value).strip()
    return default if text.casefold() in {"", "nan", "none", "nat", "null"} else text


def monitoring_risk_level(part_data):
    """Read the saved BOM risk field without inventing a status label."""
    if not isinstance(part_data, dict) and not callable(getattr(part_data, "get", None)):
        return "Needs verification"
    for key in ("Risk Level", "risk_level", "risk"):
        value = _display_text(part_data.get(key), "")
        if value:
            return value
    return "Needs verification"


def _exact_part_urls(requested_mpn, record):
    """Keep supplier/document links only when the returned MPN is exact."""
    if not isinstance(record, dict) and not callable(getattr(record, "get", None)):
        return "", ""
    returned_mpn = _display_text(
        record.get("Manufacturer Part Number")
        or record.get("manufacturer_part_number")
    )
    requested_mpn = _display_text(requested_mpn)
    if not returned_mpn or not requested_mpn:
        return "", ""
    from src.normalizer import normalize_part_number

    if normalize_part_number(returned_mpn) != normalize_part_number(requested_mpn):
        return "", ""

    from src.saved_bom_cost import http_url

    product_url = http_url(
        record.get("Product URL")
        or record.get("product_url")
        or record.get("product_detail_url")
        or record.get("source_url")
    )
    datasheet_url = http_url(
        record.get("Datasheet URL")
        or record.get("datasheet_url")
        or record.get("datasheet")
        or record.get("datasheet_link")
    )
    return product_url, datasheet_url


def build_monitor_record(
    user_id,
    analysis_id,
    part_data,
    workspace_id=None,
):
    part_number = _display_text(part_data.get("MPN", ""))
    product_url, datasheet_url = _exact_part_urls(part_number, part_data)
    return json_safe_value({
        "user_id": user_id,
        "workspace_id": workspace_id,
        "analysis_id": analysis_id,
        "part_number": part_number,
        "supplier": _display_text(part_data.get("Best Source", "")),
        "product_url": product_url,
        "datasheet_url": datasheet_url,
        "lifecycle_status": _display_text(part_data.get("Lifecycle Status", "")),
        "stock": _optional_integer(part_data.get("Stock Available")),
        "unit_price": _optional_number(part_data.get("Unit Price")),
        "risk_level": monitoring_risk_level(part_data),
    })


def resolve_monitoring_workspace_id(source_part, saved_analysis, active_workspace_id=None):
    """Use the verified saved analysis as the authoritative monitoring scope."""
    for record in (saved_analysis, source_part):
        if isinstance(record, dict):
            value = str(record.get("workspace_id") or "").strip()
            if value:
                return value
    return str(active_workspace_id or "").strip() or None


def scope_monitoring_query(query, *, user_id, workspace_id=None, analysis_id=None):
    """Scope monitoring reads to a user, workspace, and optional saved BOM.

    Part-focused links pass an analysis ID so historical alerts from another
    BOM cannot appear in the selected BOM's review. The main Monitoring page
    omits that ID and keeps its intentional workspace-wide view.
    """
    scoped = query.eq("user_id", str(user_id or ""))
    if workspace_id:
        scoped = scoped.eq("workspace_id", str(workspace_id))
    if analysis_id:
        scoped = scoped.eq("analysis_id", str(analysis_id))
    return scoped


def monitoring_route_cache_key(*, user_id, workspace_id=None, analysis_id=None):
    """Keep workspace-wide and saved-BOM monitoring snapshots in separate caches."""
    scope = f"{str(user_id or '')}:{str(workspace_id or 'personal')}"
    target = f"analysis:{str(analysis_id)}" if analysis_id else "workspace"
    return f"monitoring_route_data_{scope}:{target}"


def build_alert_record(
    user_id,
    analysis_id,
    part_number,
    alert_type,
    alert_message,
    severity,
    previous_value,
    current_value,
    workspace_id=None,
    supplier=None,
    product_url=None,
    datasheet_url=None,
):
    return {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "analysis_id": analysis_id,
        "part_number": part_number,
        "alert_type": alert_type,
        "alert_message": alert_message,
        "severity": severity,
        "previous_value": str(previous_value),
        "current_value": str(current_value),
        "supplier": _display_text(supplier),
        "product_url": _display_text(product_url),
        "datasheet_url": _display_text(datasheet_url),
    }

def detect_monitor_alerts(
    user_id,
    analysis_id,
    part_number,
    previous_snapshot,
    current_snapshot,
    workspace_id=None,
):
    alerts = []
    messages = []

    previous_stock = _optional_number(previous_snapshot.get("stock"))
    current_stock = _optional_number(current_snapshot.get("stock"))

    evidence_fields = {
        "supplier": current_snapshot.get("supplier"),
        "product_url": current_snapshot.get("product_url"),
        "datasheet_url": current_snapshot.get("datasheet_url"),
    }

    previous_price = _optional_number(previous_snapshot.get("unit_price"))
    current_price = _optional_number(current_snapshot.get("unit_price"))

    previous_lifecycle = str(previous_snapshot.get("lifecycle_status", "") or "Unknown").lower()
    current_lifecycle = str(current_snapshot.get("lifecycle_status", "") or "Unknown").lower()

    if current_lifecycle in ["", "unknown", "none", "nan"]:
        current_lifecycle = "unknown"

    if (
        previous_stock is not None
        and current_stock is not None
        and previous_stock > 0
        and current_stock < previous_stock * 0.5
    ):
        alert_message = f"Stock dropped from {previous_stock} to {current_stock}"
        messages.append(f"⚠ {alert_message}")
        alerts.append(
            build_alert_record(
                user_id,
                analysis_id,
                part_number,
                "Stock Drop",
                alert_message,
                "High",
                previous_stock,
                current_stock,
                workspace_id=workspace_id,
                **evidence_fields,
            )
        )

    if (
        previous_price is not None
        and current_price is not None
        and previous_price > 0
        and current_price > previous_price * 1.5
    ):
        alert_message = f"Unit price increased from ${previous_price:.2f} to ${current_price:.2f}"
        messages.append(f"⚠ {alert_message}")
        alerts.append(
            build_alert_record(
                user_id,
                analysis_id,
                part_number,
                "Price Increase",
                alert_message,
                "Medium",
                f"{previous_price:.2f}",
                f"{current_price:.2f}",
                workspace_id=workspace_id,
                **evidence_fields,
            )
        )

    if (
        previous_lifecycle
        and current_lifecycle
        and previous_lifecycle != "unknown"
        and current_lifecycle != "unknown"
        and previous_lifecycle != current_lifecycle
    ):
        alert_message = f"Lifecycle changed from {previous_lifecycle} to {current_lifecycle}"
        messages.append(f"⚠ {alert_message}")
        alerts.append(
            build_alert_record(
                user_id,
                analysis_id,
                part_number,
                "Lifecycle Change",
                alert_message,
                "High",
                previous_lifecycle,
                current_lifecycle,
                workspace_id=workspace_id,
                **evidence_fields,
            )
        )

    return alerts, messages


def build_updated_monitor_snapshot(
    user_id,
    part_number,
    previous_snapshot,
    fresh_data,
):
    """Build a fresh provider snapshot while retaining its saved BOM scope."""
    previous_snapshot = previous_snapshot or {}
    fresh_data = fresh_data or {}
    product_url, datasheet_url = _exact_part_urls(part_number, fresh_data)
    snapshot = {
        "user_id": user_id,
        "workspace_id": previous_snapshot.get("workspace_id"),
        "analysis_id": previous_snapshot.get("analysis_id"),
        "part_number": part_number,
        "supplier": _display_text(fresh_data.get("source", "")),
        "product_url": product_url,
        "datasheet_url": datasheet_url,
        "lifecycle_status": _display_text(fresh_data.get("lifecycle_status", "")),
        "stock": _optional_integer(fresh_data.get("stock_total")),
        "unit_price": _optional_number(fresh_data.get("unit_price")),
        "risk_level": _display_text(previous_snapshot.get("risk_level", "")),
    }
    return json_safe_value(snapshot)


def save_monitor_history(supabase, records) -> bool:
    """Persist monitoring snapshots without letting bad telemetry block analysis."""
    if not records:
        return True
    return _insert_monitor_rows(
        supabase,
        "part_monitor_history",
        records,
        optional_columns=("product_url", "datasheet_url"),
    )


def save_monitor_history_with_diagnostic(supabase, records) -> tuple[bool, str]:
    """Persist a baseline and return a safe, actionable database rejection reason."""
    if not records:
        return True, ""
    result = _insert_monitor_rows(
        supabase,
        "part_monitor_history",
        records,
        optional_columns=("product_url", "datasheet_url"),
        include_diagnostic=True,
    )
    return result


def save_monitor_alerts(supabase, records) -> bool:
    """Persist alert evidence while tolerating a not-yet-applied URL migration."""
    if not records:
        return True
    return _insert_monitor_rows(
        supabase,
        "monitor_alerts",
        records,
        optional_columns=("supplier", "product_url", "datasheet_url"),
    )


def _monitor_exception_payload(exc):
    """Read allowlisted PostgREST fields from common exception response shapes."""
    candidates = [exc]
    try:
        response = getattr(exc, "response", None)
    except Exception:
        response = None
    if response is not None:
        candidates.append(response)
        try:
            response_text = getattr(response, "text", None)
        except Exception:
            response_text = None
        if isinstance(response_text, str):
            candidates.append(response_text)
    try:
        args = getattr(exc, "args", ())
    except Exception:
        args = ()
    if isinstance(args, (tuple, list)):
        candidates.extend(args)

    def decode(candidate):
        if isinstance(candidate, dict):
            return candidate
        if isinstance(candidate, bytes):
            try:
                candidate = candidate.decode("utf-8")
            except UnicodeDecodeError:
                return {}
        if isinstance(candidate, str):
            try:
                parsed = json.loads(candidate)
            except (TypeError, ValueError):
                return {}
            return parsed if isinstance(parsed, dict) else {}
        try:
            json_method = getattr(candidate, "json", None)
            payload = json_method() if callable(json_method) else None
        except Exception:
            payload = None
        return payload if isinstance(payload, dict) else {}

    for candidate in candidates:
        payload = decode(candidate)
        if not payload:
            continue
        sources = [payload]
        for container in ("error", "data", "body"):
            nested = payload.get(container)
            if isinstance(nested, dict):
                sources.append(nested)
        fields = {}
        for source in sources:
            for field in ("code", "message", "details", "hint"):
                value = source.get(field)
                if field == "code":
                    if isinstance(value, (str, int)) and not isinstance(value, bool):
                        fields.setdefault(field, value)
                elif isinstance(value, str) and value.strip():
                    fields.setdefault(field, value.strip())
        if fields:
            return fields
    return {}


def _monitor_exception_status(exc):
    """Return a safe HTTP status code without exposing response content."""
    sources = [exc]
    try:
        response = getattr(exc, "response", None)
    except Exception:
        response = None
    if response is not None:
        sources.append(response)
    for source in sources:
        for field in ("status_code", "status"):
            try:
                value = getattr(source, field, None)
            except Exception:
                value = None
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
                return value

    try:
        code_value = getattr(exc, "code", None)
    except Exception:
        code_value = None
    if code_value is None:
        code_value = _monitor_exception_payload(exc).get("code")
    if isinstance(code_value, str) and code_value.isdigit():
        code_value = int(code_value)
    if isinstance(code_value, int) and not isinstance(code_value, bool) and 100 <= code_value <= 599:
        return code_value
    return None


def _monitor_exception_text(exc, payload=None):
    """Read structured PostgREST fields for internal classification only."""
    parts = []
    try:
        text = str(exc or "").strip()
    except Exception:
        text = ""
    if text:
        parts.append(text)
    for field in ("message", "details", "hint"):
        try:
            value = getattr(exc, field, None)
        except Exception:
            value = None
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    payload = payload if isinstance(payload, dict) else _monitor_exception_payload(exc)
    for field in ("message", "details", "hint"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n".join(parts)


def _monitor_persistence_diagnostic(exc):
    """Summarize PostgREST failures without echoing submitted snapshot contents."""
    payload = _monitor_exception_payload(exc)
    raw = _monitor_exception_text(exc, payload)
    folded = raw.casefold()

    try:
        code_value = getattr(exc, "code", None)
    except Exception:
        code_value = None
    if code_value is None:
        code_value = payload.get("code")
    code = ""
    if isinstance(code_value, (str, int)) and not isinstance(code_value, bool):
        structured_code = re.fullmatch(
            r"(?:PGRST\d{3}|\d{5})",
            str(code_value).strip(),
            re.IGNORECASE,
        )
        if structured_code:
            code = structured_code.group(0).upper()
    if not code:
        code_match = re.search(r"\b(?:PGRST\d{3}|\d{5})\b", raw, re.IGNORECASE)
        code = code_match.group(0).upper() if code_match else ""

    constraint_match = re.search(
        r'\bconstraint\s+["\']([A-Za-z_][A-Za-z0-9_$]*)["\']',
        raw,
        re.IGNORECASE,
    )
    constraint = constraint_match.group(1) if constraint_match else ""

    def with_metadata(message):
        metadata = []
        if code:
            metadata.append(f"database code {code}")
        if constraint:
            metadata.append(f"constraint {constraint}")
        suffix = f" ({'; '.join(metadata)})" if metadata else ""
        return f"{message}{suffix}"

    if "row-level security" in folded or "permission denied" in folded or code == "42501":
        return with_metadata("The database write policy rejected the monitoring baseline.")
    if "foreign key" in folded or code == "23503":
        return with_metadata("The saved BOM or workspace reference was rejected by the database.")
    if "not-null" in folded or "null value" in folded or code == "23502":
        return with_metadata("A required monitoring field is missing from the baseline.")
    if "duplicate key" in folded or code == "23505":
        return with_metadata("The database reports an existing baseline with the same unique key.")
    if "column" in folded or "schema cache" in folded or code.startswith("PGRST2"):
        return with_metadata(
            "The monitoring database schema is missing a field. Apply the current monitoring migrations."
        )
    if "check constraint" in folded or code == "23514":
        return with_metadata(
            "The monitoring database rejected a field value. Apply the current monitoring migrations and retry."
        )
    error_class = type(exc)
    qualified_type = ".".join(
        part for part in (getattr(error_class, "__module__", ""), getattr(error_class, "__qualname__", error_class.__name__))
        if part and part != "builtins"
    )
    error_type = re.sub(r"[^A-Za-z0-9_.]", "", qualified_type) or "UnknownError"
    metadata = [f"error type {error_type}"]
    status = _monitor_exception_status(exc)
    if status:
        metadata.append(f"HTTP status {status}")
    if code:
        metadata.append(f"database code {code}")
    if constraint:
        metadata.append(f"constraint {constraint}")
    if not raw and not payload:
        metadata.append("structured response fields unavailable")
    suffix = f" ({'; '.join(metadata)})"
    return f"The monitoring baseline could not be saved{suffix}. Check the server log for the database error."


def _insert_monitor_rows(
    supabase,
    table_name,
    records,
    *,
    optional_columns,
    include_diagnostic=False,
):
    pending = json_safe_value(records)
    while True:
        try:
            supabase.table(table_name).insert(pending).execute()
            return (True, "") if include_diagnostic else True
        except Exception as exc:
            folded = _monitor_exception_text(exc).casefold()
            missing_column = next(
                (
                    column
                    for column in optional_columns
                    if column in folded
                    and ("column" in folded or "schema cache" in folded)
                    and any(column in row for row in pending)
                ),
                "",
            )
            if missing_column:
                pending = [
                    {key: value for key, value in row.items() if key != missing_column}
                    for row in pending
                ]
                continue
            diagnostic = _monitor_persistence_diagnostic(exc)
            _logger.warning(
                "Could not save %s monitoring data (%s): %s",
                table_name,
                type(exc).__name__,
                diagnostic,
            )
            return (False, diagnostic) if include_diagnostic else False


def detect_monitored_part_changes(
    user_id,
    part_number,
    previous_snapshot,
    current_snapshot,
):
    """Compare two snapshots using the detector's analysis/workspace scope."""
    previous_snapshot = previous_snapshot or {}
    current_snapshot = current_snapshot or {}
    analysis_id = (
        current_snapshot.get("analysis_id")
        or previous_snapshot.get("analysis_id")
    )
    workspace_id = (
        current_snapshot.get("workspace_id")
        or previous_snapshot.get("workspace_id")
    )
    return detect_monitor_alerts(
        user_id,
        analysis_id,
        part_number,
        previous_snapshot,
        current_snapshot,
        workspace_id=workspace_id,
    )


def monitoring_entitlement_message(plan_name, monitored_count, monitored_limit, is_admin=False):
    """Return a launch-safe monitoring limit message for UI and service checks."""
    if is_admin or monitored_limit is None:
        return True, "Unlimited monitoring is available."
    if monitored_limit <= 0:
        return False, f"Monitoring is not included with {plan_name}. Upgrade to Professional to monitor up to 2,500 components."
    if monitored_count >= monitored_limit:
        return False, f"Your {plan_name} workspace has reached its {monitored_limit:,}-part monitoring limit. Existing monitoring remains active; upgrade to Business for unlimited monitoring."
    remaining = monitored_limit - monitored_count
    return True, f"{remaining:,} monitoring slot(s) remain."
