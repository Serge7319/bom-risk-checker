def build_monitor_record(user_id, analysis_id, part_data):
    return {
        "user_id": user_id,
        "analysis_id": analysis_id,
        "part_number": part_data.get("MPN", ""),
        "supplier": part_data.get("Best Source", ""),
        "lifecycle_status": part_data.get("Lifecycle Status", ""),
        "stock": part_data.get("Stock Available", 0),
        "unit_price": part_data.get("Unit Price", 0.0),
        "risk_level": part_data.get("Risk Level", ""),
    }

def build_alert_record(
    user_id,
    analysis_id,
    part_number,
    alert_type,
    alert_message,
    severity,
    previous_value,
    current_value,
):
    return {
        "user_id": user_id,
        "analysis_id": analysis_id,
        "part_number": part_number,
        "alert_type": alert_type,
        "alert_message": alert_message,
        "severity": severity,
        "previous_value": str(previous_value),
        "current_value": str(current_value),
    }

def detect_monitor_alerts(user_id, analysis_id, part_number, previous_snapshot, current_snapshot):
    alerts = []
    messages = []

    previous_stock = previous_snapshot.get("stock", 0) or 0
    current_stock = current_snapshot.get("stock", 0) or 0

    previous_price = float(previous_snapshot.get("unit_price", 0) or 0)
    current_price = float(current_snapshot.get("unit_price", 0) or 0)

    previous_lifecycle = str(previous_snapshot.get("lifecycle_status", "") or "Unknown").lower()
    current_lifecycle = str(current_snapshot.get("lifecycle_status", "") or "Unknown").lower()

    if current_lifecycle in ["", "unknown", "none", "nan"]:
        current_lifecycle = "unknown"

    if previous_stock > 0 and current_stock < previous_stock * 0.5:
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
            )
        )

    if previous_price > 0 and current_price > previous_price * 1.5:
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
            )
        )

    return alerts, messages