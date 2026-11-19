"""Opt-in live supplier monitoring and protected scheduled runs.

The scheduled path polls only workspaces with an authenticated member opt-in.
Supplier calls and automatic email are separately gated; read-only views and
explicit alert refreshes never call vendors or send mail.
"""
from __future__ import annotations

import hmac
import inspect
import os
from datetime import datetime, timezone
from typing import Any, Callable

from apps.api import migration_tools, monitoring_store, slack_notifications
from apps.api.workspace_store import get_store
from src.normalizer import normalize_part_number


def scheduler_enabled() -> bool:
    return (os.environ.get("CADIVOR_MONITORING_SCHEDULER_ENABLED") or "").strip() == "1"


def cron_token_configured() -> bool:
    return bool((os.environ.get("CADIVOR_MONITORING_CRON_TOKEN") or "").strip())


def schedule_attached() -> bool:
    """Operator confirmation that the six-hour workflow and secret are attached."""
    return (os.environ.get("CADIVOR_MONITORING_SCHEDULE_ATTACHED") or "").strip() == "1"


def live_supplier_refresh_enabled() -> bool:
    return (os.environ.get("CADIVOR_MONITORING_LIVE_SUPPLIER_REFRESH_ENABLED") or "").strip() == "1"


def configured_supplier_count() -> int:
    try:
        from apps.api.legacy_supplier_workflow import configured_supplier_count as count

        return int(count())
    except Exception:  # noqa: BLE001
        return 0


def supplier_refresh_readiness() -> dict[str, Any]:
    enabled = live_supplier_refresh_enabled()
    providers = configured_supplier_count()
    missing = []
    if not enabled:
        missing.append("live supplier refresh is disabled")
    if providers <= 0:
        missing.append("authorized distributor credentials are not configured")
    if enabled and providers > 0:
        status = "ready"
    elif enabled or providers > 0:
        status = "partial"
    else:
        status = "not_connected"
    return {
        "status": status,
        "enabled": enabled,
        "configured_supplier_count": providers,
        "detail": "Live monitoring polls exact MPNs through configured authorized distributors.",
        "missing_requirements": missing,
    }


def scheduler_readiness() -> dict[str, Any]:
    """Report ready only when code, live provider access, token and cron exist."""
    enabled = scheduler_enabled()
    cron = cron_token_configured()
    attached = schedule_attached()
    live = live_supplier_refresh_enabled()
    providers = configured_supplier_count()
    missing = []
    if not enabled:
        missing.append("scheduler feature flag")
    if not cron:
        missing.append("cron authentication token")
    if not attached:
        missing.append("six-hour schedule attachment")
    if not live:
        missing.append("live supplier refresh feature flag")
    if providers <= 0:
        missing.append("at least one authorized distributor credential")
    if not enabled and not any((cron, attached, live)):
        status = "not_connected"
    elif enabled and cron and attached and live and providers > 0:
        status = "ready"
    else:
        status = "partial"
    return {
        "status": status,
        "enabled": enabled,
        "cron_token_configured": cron,
        "schedule_attached": attached,
        "live_supplier_refresh_enabled": live,
        "configured_supplier_count": providers,
        "cadence_hours": 6,
        "missing_requirements": missing,
        "detail": (
            "Only opted-in workspaces are polled. A scheduled check requires the cron "
            "workflow, token, live supplier refresh gate, and at least one configured distributor."
        ),
    }


def authorize_cron(header_token: str | None) -> bool:
    expected = (os.environ.get("CADIVOR_MONITORING_CRON_TOKEN") or "").strip()
    supplied = (header_token or "").strip()
    return bool(expected and supplied and hmac.compare_digest(supplied, expected))


def _first_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def _optional_number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return int(result) if result.is_integer() else result


def _baseline(part: dict[str, Any]) -> dict[str, Any]:
    stock = _optional_number(_first_value(
        part, "Total Market Stock", "Stock Available", "Stock", "stock",
        "total_market_stock", "stock_total",
    ))
    price = _optional_number(_first_value(part, "Unit Price", "unit_price", "price", "best_price"))
    if price is not None and price <= 0:
        price = None
    lead_time = _optional_number(
        _first_value(part, "Lead Time Weeks", "lead_time_weeks", "lead_time")
    )
    return {
        "stock": stock,
        "unit_price": price,
        "lead_time_weeks": lead_time,
        "lifecycle_status": str(_first_value(part, "Lifecycle", "lifecycle_status") or "Unknown"),
        "risk_level": str(_first_value(part, "Risk Level", "risk_level", "Risk", "risk") or ""),
        "supplier": str(_first_value(part, "Best Source", "source") or "Saved analysis"),
        "product_url": str(_first_value(part, "Product URL", "product_detail_url", "product_url") or ""),
        "datasheet_url": str(_first_value(part, "Datasheet URL", "datasheet_url") or ""),
    }


def _send_weekly_monitoring_digest(workspace_id: str, member: dict[str, Any]) -> bool:
    """Send a once-per-seven-days monitoring digest to an opted-in member."""
    import html

    user_id = str(member.get("user_id") or "").strip()
    recipient = str(member.get("email") or "").strip()
    if not user_id or not recipient or not monitoring_store.email_transport_ready():
        return False
    try:
        preferences = monitoring_store.get_user_preferences(
            workspace_id, user_id, recipient
        )
    except Exception:  # noqa: BLE001
        return False
    if not preferences.get("email_alerts"):
        return False
    if not monitoring_store.claim_weekly_digest_email(workspace_id, user_id):
        return False

    cutoff = datetime.now(timezone.utc).timestamp() - 7 * 86400
    digest_alerts: list[dict[str, Any]] = []
    for alert in monitoring_store.list_alerts(workspace_id):
        if alert.get("active") is False or str(alert.get("status") or "active").lower() == "inactive":
            continue
        try:
            created = datetime.fromisoformat(
                str(alert.get("created_at") or "").replace("Z", "+00:00")
            )
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if created.timestamp() < cutoff:
            continue
        alert_type = str(alert.get("alert_type") or "").casefold()
        category = (
            "lifecycle" if "lifecycle" in alert_type else
            "availability" if any(term in alert_type for term in ("stock", "availability", "inventory", "lead time", "lead_time")) else
            "risk"
        )
        if preferences.get(category, True):
            digest_alerts.append(alert)

    digest_alerts.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    displayed = digest_alerts[:15]
    text_lines = ["Cadivor weekly monitoring digest", ""]
    html_rows = []
    for alert in displayed:
        part = str(alert.get("part_number") or "Component")
        kind = str(alert.get("alert_type") or "Monitoring alert")
        message = str(alert.get("alert_message") or alert.get("message") or "Review the monitoring alert in Cadivor.")
        text_lines.append(f"{kind} · {part}: {message}")
        html_rows.append(
            "<li><strong>" + html.escape(kind) + " · " + html.escape(part)
            + "</strong><br>" + html.escape(message) + "</li>"
        )
    if not displayed:
        text_lines.append("No new active monitoring alerts were recorded in the past seven days.")
        html_body = "<p>No new active monitoring alerts were recorded in the past seven days.</p>"
    else:
        omitted = len(digest_alerts) - len(displayed)
        if omitted:
            text_lines.extend(["", f"{omitted} additional alert(s) are available in Cadivor Monitoring."])
        html_body = "<ul>" + "".join(html_rows) + "</ul>"
        if omitted:
            html_body += f"<p>{omitted} additional alert(s) are available in Cadivor Monitoring.</p>"
    html_body = (
        "<h2>Cadivor weekly monitoring digest</h2>"
        + html_body
        + '<p><a href="https://app.cadivor.com/monitoring">Open Monitoring</a></p>'
        + "<p>Manage alert preferences in Cadivor Settings.</p>"
    )
    try:
        from src.email_delivery import send_transactional_email

        send_transactional_email(
            to_email=recipient,
            subject="Cadivor weekly monitoring digest",
            html_body=html_body,
            text_body="\n".join(text_lines) + "\n\nOpen Monitoring: https://app.cadivor.com/monitoring",
        )
        monitoring_store.finish_weekly_digest_email(
            workspace_id, user_id, delivered=True
        )
        return True
    except Exception:  # noqa: BLE001
        monitoring_store.finish_weekly_digest_email(
            workspace_id, user_id, delivered=False
        )
        return False


def _supplier_lookup(mpn: str, manufacturer: str = "") -> dict[str, Any]:
    """Call Cadivor's existing authorized distributor aggregator."""
    from integrations.supplier_aggregator import get_best_part_data

    result = get_best_part_data(mpn, manufacturer=manufacturer)
    return result if isinstance(result, dict) else {}


def run_live_analysis_refresh(
    workspace_id: str,
    analysis_id: str,
    *,
    part_number: str | None = None,
    supplier_lookup: Callable[..., dict[str, Any]] | None = None,
    dry_run: bool = False,
    scheduled: bool = False,
    progress_callback: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Poll exact MPNs, persist matched snapshots and change alerts.

    Dry runs only count candidate parts and never call the supplier adapter or
    write snapshots, alerts, history, or notifications.
    """
    if not live_supplier_refresh_enabled():
        return {"ok": False, "status": "blocked", "reason": "live_supplier_refresh_disabled", "supplier_calls": 0}
    if supplier_lookup is None and configured_supplier_count() <= 0:
        return {"ok": False, "status": "blocked", "reason": "supplier_credentials_missing", "supplier_calls": 0}
    aid = str(analysis_id or "").strip()
    wid = str(workspace_id or "").strip()
    if not aid or not wid:
        return {"ok": False, "status": "invalid_scope", "supplier_calls": 0}
    report = migration_tools.get_report(aid, workspace_id=wid)
    if not report:
        return {"ok": False, "status": "not_found", "supplier_calls": 0}
    wanted = normalize_part_number(str(part_number or ""))
    parts = [
        row for row in (report.get("parts") or [])
        if isinstance(row, dict)
        and str(row.get("MPN") or row.get("mpn") or "").strip()
        and (not wanted or normalize_part_number(str(row.get("MPN") or row.get("mpn"))) == wanted)
    ]
    if wanted and not parts:
        return {"ok": False, "status": "part_not_in_analysis", "supplier_calls": 0}
    if dry_run:
        return {
            "ok": True,
            "status": "dry_run",
            "workspace_id": wid,
            "analysis_id": aid,
            "candidate_parts": len(parts),
            "supplier_calls": 0,
            "persisted": False,
            "email_sent": False,
        }

    lookup = supplier_lookup or _supplier_lookup
    from src.monitoring_engine import detect_monitor_alerts

    checked: list[dict[str, Any]] = []
    new_alerts: list[dict[str, Any]] = []
    calls = 0
    for part in parts:
        if progress_callback is not None:
            try:
                progress_callback()
            except Exception:  # noqa: BLE001
                # Heartbeat bookkeeping must not interrupt supplier polling.
                pass
        mpn = str(part.get("MPN") or part.get("mpn") or "").strip()
        requested_manufacturer = str(
            part.get("Manufacturer") or part.get("manufacturer") or ""
        ).strip()
        calls += 1
        try:
            try:
                signature = inspect.signature(lookup)
                supports_manufacturer = (
                    "manufacturer" in signature.parameters
                    or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in signature.parameters.values()
                    )
                )
            except (TypeError, ValueError):
                supports_manufacturer = lookup is _supplier_lookup
            fresh = (
                lookup(mpn, manufacturer=requested_manufacturer)
                if supports_manufacturer
                else lookup(mpn)
            ) or {}
        except Exception:  # noqa: BLE001
            checked.append({"part_number": mpn, "status": "supplier_unavailable"})
            continue
        returned = str(fresh.get("manufacturer_part_number") or "").strip()
        if (
            not fresh.get("supplier_data_verified")
            or normalize_part_number(returned) != normalize_part_number(mpn)
        ):
            checked.append({"part_number": mpn, "status": "exact_supplier_match_unavailable"})
            continue
        returned_manufacturer = str(fresh.get("manufacturer") or "").strip()
        if requested_manufacturer:
            try:
                from apps.api.manufacturer_identity import manufacturers_match

                maker_matches = manufacturers_match(
                    requested_manufacturer, returned_manufacturer, mpn=mpn
                )
            except Exception:  # noqa: BLE001
                maker_matches = bool(
                    returned_manufacturer
                    and returned_manufacturer.casefold() == requested_manufacturer.casefold()
                )
            if not maker_matches:
                checked.append({"part_number": mpn, "status": "manufacturer_identity_mismatch"})
                continue

        stock = _optional_number(_first_value(
            fresh, "total_market_stock", "stock_total", "stock", "Stock", "Stock Available"
        ))
        price = _optional_number(_first_value(fresh, "unit_price", "price", "best_price"))
        lead_time = _optional_number(
            _first_value(fresh, "lead_time_weeks", "Lead Time Weeks", "lead_time")
        )
        if price is not None and price <= 0:
            price = None
        retrieved_at = datetime.now(timezone.utc).isoformat()
        current = {
            "workspace_id": wid,
            "analysis_id": aid,
            "part_number": mpn,
            "manufacturer_part_number": returned,
            "manufacturer": returned_manufacturer,
            "supplier": str(fresh.get("source") or "").strip(),
            "stock": stock,
            "unit_price": price,
            "lead_time_weeks": lead_time,
            "currency": str(fresh.get("unit_price_currency") or fresh.get("currency") or "").strip(),
            "lifecycle_status": str(fresh.get("lifecycle_status") or "Unknown").strip(),
            "product_url": str(fresh.get("product_detail_url") or fresh.get("product_url") or "").strip(),
            "datasheet_url": str(fresh.get("datasheet_url") or "").strip(),
            "retrieved_at": retrieved_at,
            "evidence_source": "live-authorized-supplier",
            "identity_verified": True,
        }
        from src.risk_engine import calculate_risk

        assessed_risk = calculate_risk({
            **fresh,
            "stock_total": stock,
            "stock_data_complete": bool(fresh.get("stock_data_complete")),
            "lead_time_weeks": lead_time,
            "lifecycle_status": current["lifecycle_status"],
            "quantity": _optional_number(_first_value(part, "Quantity", "quantity")),
        })
        current["risk_level"] = str(assessed_risk.get("risk_level") or "Needs verification")
        previous = monitoring_store.get_live_snapshot(wid, aid, mpn) or _baseline(part)
        observed_fields = []
        field_retrieved_at = dict(previous.get("field_retrieved_at") or {})
        comparison_current = dict(previous)
        for field in ("stock", "unit_price", "lead_time_weeks"):
            if current[field] is not None:
                comparison_current[field] = current[field]
                observed_fields.append(field)
                field_retrieved_at[field] = retrieved_at
        if current["lifecycle_status"].casefold() not in {"", "unknown", "none", "nan"}:
            comparison_current["lifecycle_status"] = current["lifecycle_status"]
            observed_fields.append("lifecycle_status")
            field_retrieved_at["lifecycle_status"] = retrieved_at
        if current.get("risk_level") in {"High", "Medium", "Low"}:
            comparison_current["risk_level"] = current["risk_level"]
            observed_fields.append("risk_level")
        if not observed_fields:
            checked.append({"part_number": mpn, "status": "no_usable_measurements"})
            continue
        current.update({
            "stock": comparison_current.get("stock"),
            "unit_price": comparison_current.get("unit_price"),
            "lead_time_weeks": comparison_current.get("lead_time_weeks"),
            "lifecycle_status": comparison_current.get("lifecycle_status", "Unknown"),
            "risk_level": current.get("risk_level"),
            "observed_fields": observed_fields,
            "field_retrieved_at": field_retrieved_at,
        })
        detected, _messages = detect_monitor_alerts(
            "scheduled-monitor", aid, mpn, previous, comparison_current, workspace_id=wid
        )
        for alert in detected:
            alert.update({
                "analysis_id": aid,
                "workspace_id": wid,
                "part_number": mpn,
                "active": True,
                "status": "active",
                "evidence_source": "live-authorized-supplier",
                "retrieved_at": retrieved_at,
                "supplier": current["supplier"],
                "product_url": current["product_url"],
                "datasheet_url": current["datasheet_url"],
            })
        saved_alerts = monitoring_store.reconcile_alerts(
            wid, analysis_id=aid, active_alerts=detected, part_number=mpn
        )
        alert_keys = {
            (str(row.get("part_number") or "").casefold(), str(row.get("alert_type") or ""))
            for row in detected
        }
        new_alerts.extend(
            row for row in saved_alerts
            if (str(row.get("part_number") or "").casefold(), str(row.get("alert_type") or "")) in alert_keys
        )
        monitoring_store.save_live_snapshot(current)
        checked.append({"part_number": mpn, "status": "updated", "alert_count": len(detected), "retrieved_at": retrieved_at})

    refresh = monitoring_store.record_refresh(
        wid,
        analysis_id=aid,
        alert_count=len(new_alerts),
        mode="live-authorized-supplier",
        scope="part" if wanted else "analysis",
        part_number=str(part_number or "").strip() or None,
        scheduled=scheduled,
    )
    return {
        "ok": True,
        "status": "updated",
        "workspace_id": wid,
        "analysis_id": aid,
        "scope": "part" if wanted else "analysis",
        "supplier_calls": calls,
        "updated_parts": sum(row["status"] == "updated" for row in checked),
        "failed_parts": [row for row in checked if row["status"] != "updated"],
        "alert_count": len(new_alerts),
        "alerts": new_alerts,
        "refresh": refresh,
        "persisted": True,
        "live_supplier_refresh": True,
        "email_sent": False,
    }


def run_scheduled_cycle(
    *,
    dry_run: bool = False,
    progress_callback: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Run six-hour supplier checks for workspaces with member opt-in."""
    def _report_progress() -> None:
        if progress_callback is None:
            return
        try:
            progress_callback()
        except Exception:  # noqa: BLE001
            # Progress bookkeeping must not interrupt a supplier refresh.
            pass

    try:
        scopes = get_store().list_monitoring_analyses()
    except Exception:  # noqa: BLE001
        return {"ok": False, "status": "blocked", "reason": "workspace_store_unavailable", "supplier_calls": 0}
    opted_in = monitoring_store.list_user_preferences(supplier_checks=True)
    workspaces = {str(row.get("workspace_id") or "") for row in opted_in}
    scopes_by_workspace: dict[str, list[dict[str, Any]]] = {}
    for row in scopes:
        wid = str(row.get("workspace_id") or "")
        if wid in workspaces:
            scopes_by_workspace.setdefault(wid, []).append(row)
    targets: list[dict[str, Any]] = []
    for wid, workspace_scopes in scopes_by_workspace.items():
        capacity = monitoring_store.get_workspace_monitoring_capacity(wid)
        if capacity is None:
            targets.extend(workspace_scopes)
            continue
        included_parts = 0
        for scope in workspace_scopes:
            part_count = max(0, int(scope.get("total_parts") or 0))
            if included_parts + part_count <= capacity:
                targets.append(scope)
                included_parts += part_count
    if dry_run:
        return {
            "ok": True,
            "status": "dry_run",
            "analysis_count": len(targets),
            "supplier_calls": 0,
            "email_sent": False,
            "persisted": False,
            "scheduler_enabled": scheduler_enabled(),
            "live_supplier_refresh_enabled": live_supplier_refresh_enabled(),
            "configured_supplier_count": configured_supplier_count(),
            "opted_in_workspace_count": len(workspaces),
        }
    if not scheduler_enabled():
        return {"ok": False, "status": "blocked", "reason": "scheduler_disabled", "supplier_calls": 0}
    if not live_supplier_refresh_enabled():
        return {"ok": False, "status": "blocked", "reason": "live_supplier_refresh_disabled", "supplier_calls": 0}
    if configured_supplier_count() <= 0:
        return {"ok": False, "status": "blocked", "reason": "supplier_credentials_missing", "supplier_calls": 0}

    summary = {"ok": True, "status": "complete", "analysis_count": len(targets), "supplier_calls": 0, "updated_parts": 0, "alert_count": 0, "email_sent": 0, "digest_emails_sent": 0, "slack_sent": 0, "failures": []}
    email_members: dict[str, list[dict[str, Any]]] = {}
    new_alerts_by_workspace: dict[str, dict[str, dict[str, Any]]] = {}
    for row in monitoring_store.list_user_preferences(email_alerts=True):
        email_members.setdefault(str(row.get("workspace_id") or ""), []).append(row)
    for scope in targets:
        result = run_live_analysis_refresh(
            str(scope["workspace_id"]),
            str(scope["analysis_id"]),
            scheduled=True,
            progress_callback=progress_callback,
        )
        summary["supplier_calls"] += int(result.get("supplier_calls") or 0)
        summary["updated_parts"] += int(result.get("updated_parts") or 0)
        summary["alert_count"] += int(result.get("alert_count") or 0)
        if not result.get("ok"):
            summary["failures"].append({"workspace_id": scope["workspace_id"], "analysis_id": scope["analysis_id"], "reason": result.get("reason") or result.get("status")})
            _report_progress()
            continue
        workspace_id = str(scope["workspace_id"])
        candidates = new_alerts_by_workspace.setdefault(workspace_id, {})
        for failed_part in result.get("failed_parts") or []:
            summary["failures"].append({
                "workspace_id": scope["workspace_id"],
                "analysis_id": scope["analysis_id"],
                "part_number": failed_part.get("part_number"),
                "reason": failed_part.get("status") or "supplier_data_unavailable",
            })
        for alert in result.get("alerts") or []:
            alert_id = str(alert.get("id") or "").strip()
            if alert_id and alert.get("evidence_source") == "live-authorized-supplier":
                candidates[alert_id] = alert
        _report_progress()

    # A workspace sends one aggregate Slack message for new and retryable
    # alerts. Delivery receipts prevent duplicates and retain transient failures.
    slack_workspaces = set(new_alerts_by_workspace)
    for row in opted_in:
        wid = str(row.get("workspace_id") or "")
        if wid and monitoring_store.list_retryable_slack_alert_ids(wid):
            slack_workspaces.add(wid)
    all_workspace_alerts: dict[str, dict[str, dict[str, Any]]] = {}
    for workspace_id in slack_workspaces:
        if not workspace_id:
            continue
        alerts_by_id = {
            str(alert.get("id") or ""): alert
            for alert in monitoring_store.list_alerts(workspace_id)
            if str(alert.get("id") or "").strip()
        }
        alerts_by_id.update(new_alerts_by_workspace.get(workspace_id, {}))
        all_workspace_alerts[workspace_id] = alerts_by_id
        ciphertext = monitoring_store.workspace_slack_ciphertext(workspace_id)
        if not ciphertext:
            continue
        retryable_ids = set(monitoring_store.list_retryable_slack_alert_ids(workspace_id))
        candidate_ids = set(new_alerts_by_workspace.get(workspace_id, {})) | retryable_ids
        claimed: list[dict[str, Any]] = []
        for alert_id in sorted(candidate_ids):
            alert = alerts_by_id.get(alert_id)
            if not alert or alert.get("evidence_source") != "live-authorized-supplier":
                continue
            is_retry = alert_id in retryable_ids
            if not is_retry and (
                alert.get("active") is False
                or str(alert.get("status") or "active").lower() == "inactive"
            ):
                continue
            if monitoring_store.claim_scheduled_slack_alert(workspace_id, alert_id):
                claimed.append(alert)
        if not claimed:
            continue
        delivered = slack_notifications.deliver_workspace_alert(ciphertext, claimed)
        for alert in claimed:
            monitoring_store.finish_scheduled_slack_alert(
                workspace_id, str(alert.get("id") or ""), delivered=delivered
            )
        if delivered:
            summary["slack_sent"] += 1
        else:
            summary["failures"].append({
                "workspace_id": workspace_id,
                "reason": "slack_delivery_failed",
            })

    # Retry prior failed mail independently of whether this refresh observed a
    # fresh value change. A later poll must not erase a notification event.
    for workspace_id, members in email_members.items():
        if not workspace_id:
            continue
        alerts_by_id = all_workspace_alerts.get(workspace_id) or {
            str(alert.get("id") or ""): alert
            for alert in monitoring_store.list_alerts(workspace_id)
            if str(alert.get("id") or "").strip()
        }
        for alert_id, alert in new_alerts_by_workspace.get(workspace_id, {}).items():
            alerts_by_id[alert_id] = alert
        for member in members:
            user_id = str(member.get("user_id") or "")
            retryable_ids = set(
                monitoring_store.list_retryable_scheduled_alert_ids(workspace_id, user_id)
            )
            candidates = set(new_alerts_by_workspace.get(workspace_id, {})) | retryable_ids
            for alert_id in candidates:
                alert = alerts_by_id.get(alert_id)
                if not alert:
                    continue
                is_retry = alert_id in retryable_ids
                if not is_retry and (
                    alert.get("active") is False
                    or str(alert.get("status") or "active").lower() == "inactive"
                ):
                    continue
                if not monitoring_store.claim_scheduled_alert_email(
                    workspace_id, user_id, alert
                ):
                    continue
                delivery = monitoring_store.deliver_alert_email(
                    workspace_id,
                    alert,
                    user_id=user_id,
                    recipient_email=str(member.get("email") or ""),
                )
                monitoring_store.finish_scheduled_alert_email(
                    workspace_id,
                    user_id,
                    alert,
                    delivered=bool(delivery.get("delivered")),
                    retry=str(delivery.get("reason") or "") not in {
                        "preferences_disabled",
                        "lifecycle_notifications_disabled",
                        "availability_notifications_disabled",
                        "risk_notifications_disabled",
                    },
                )
                if delivery.get("delivered"):
                    summary["email_sent"] += 1
                else:
                    summary["failures"].append({
                        "workspace_id": workspace_id,
                        "user_id": user_id,
                        "alert_id": alert_id,
                        "reason": delivery.get("reason") or "email_delivery_failed",
                    })
                _report_progress()
    for member in monitoring_store.list_user_preferences(
        email_alerts=True, weekly_digest=True
    ):
        if _send_weekly_monitoring_digest(
            str(member.get("workspace_id") or ""), member
        ):
            summary["digest_emails_sent"] += 1
    if summary["failures"]:
        summary["status"] = "completed_with_failures"
    return summary


def run_workspace_refresh(
    workspace_id: str,
    *,
    analysis_id: str | None = None,
    part_number: str | None = None,
    portfolio: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Re-derive saved-analysis alerts; this path never calls suppliers or emails."""
    part = str(part_number or "").strip() or None
    if dry_run:
        if portfolio:
            raise ValueError("dry_run supports a single analysis_id scope")
        payload = migration_tools.monitoring_payload(
            workspace_id=workspace_id, analysis_id=analysis_id
        )
        alerts = list(payload.get("alerts") or [])
        if part:
            alerts = [a for a in alerts if str(a.get("part_number") or "").casefold() == part.casefold()]
        return {
            "ok": True,
            "dry_run": True,
            "workspace_id": workspace_id,
            "scope": "part" if part else "analysis",
            "analysis_id": payload.get("analysis_id") or analysis_id,
            "part_number": part,
            "scheduler_enabled": scheduler_enabled(),
            "email_delivery_enabled": monitoring_store.email_delivery_enabled(),
            "alert_count": len(alerts),
            "alerts": alerts,
            "refresh": None,
            "notifications": [],
            "email_sent": False,
            "persisted": False,
            "gap": "Dry run: nothing was saved and no notifications were attempted.",
        }
    payload = migration_tools.monitoring_refresh_payload(
        workspace_id=workspace_id,
        analysis_id=analysis_id,
        part_number=part,
        portfolio=portfolio,
    )
    return {
        "ok": True,
        "dry_run": False,
        "persisted": True,
        "workspace_id": workspace_id,
        "scope": payload.get("scope"),
        "scope_label": payload.get("scope_label"),
        "analysis_id": payload.get("analysis_id"),
        "part_number": payload.get("part_number"),
        "scheduler_enabled": scheduler_enabled(),
        "email_delivery_enabled": monitoring_store.email_delivery_enabled(),
        "alert_count": payload.get("alert_count", len(payload.get("alerts") or [])),
        "alerts": payload.get("alerts") or [],
        "refresh": payload.get("refresh"),
        "live_supplier_refresh": False,
        "notifications": [],
        "email_sent": False,
        "gap": (
            "Saved-analysis alert refresh only; never sends email. Use supplier refresh "
            "for live vendor checks and Notify for explicit email actions."
        ),
    }
