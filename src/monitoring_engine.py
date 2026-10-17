import logging
import math

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


def _display_text(value, default=""):
    value = json_safe_value(value)
    if value is None:
        return default
    text = str(value).strip()
    return default if text.casefold() in {"", "nan", "none", "nat", "null"} else text


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
        "stock": _optional_number(part_data.get("Stock Available")),
        "unit_price": _optional_number(part_data.get("Unit Price")),
        "risk_level": _display_text(part_data.get("Risk Level", "")),
    })

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
        "stock": _optional_number(fresh_data.get("stock_total")),
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


def _insert_monitor_rows(supabase, table_name, records, *, optional_columns):
    pending = json_safe_value(records)
    while True:
        try:
            supabase.table(table_name).insert(pending).execute()
            return True
        except Exception as exc:
            folded = str(exc).casefold()
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
            _logger.warning(
                "Could not save %s monitoring data (%s)",
                table_name,
                type(exc).__name__,
            )
            return False


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
