"""Server-side anonymous BOM teaser. Never return locked component evidence to the browser."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import ipaddress
import math
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import pandas as pd

from integrations.stock_coercion import parse_stock_total, stock_evidence_note
from src.normalizer import normalize_part_number
from src.secrets import get_secret

MAX_BYTES = 1_000_000
MAX_ROWS = 30
PREVIEW_ROWS = 5
MAX_XLSX_UNCOMPRESSED = 8_000_000
VISITOR_HEADER = "X-Cadivor-Visitor"
PUBLIC_BOM_LIMIT_MESSAGE = "This connection has used its two free BOM audits in the last 24 hours."
PUBLIC_BOM_EMAIL_QUOTA_MESSAGE = (
    "This email already used its free complete BOM audit in the last 30 days."
)
PUBLIC_BOM_BUDGET_MESSAGE = (
    "The free BOM audit has reached today's supplier lookup budget. Please try again tomorrow."
)
VERIFICATION_RESEND_COOLDOWN_SECONDS = 15 * 60
FULL_ENRICHMENT_WINDOW_DAYS = 30
FULL_ENRICHMENT_LEASE_SECONDS = 15 * 60
PUBLIC_BOM_COMPLETE_IN_PROGRESS_MESSAGE = (
    "Your complete audit is still being prepared. Refresh in a moment."
)
# Default global UTC-day cap on supplier-enriched rows (preview + complete).
# Tune via CADIVOR_PUBLIC_BOM_DAILY_ENRICHED_ROWS. Providers have no coded daily
# caps beyond per-search limit≤25; 500 ≈ 100 anonymous 5-row previews.
DEFAULT_DAILY_ENRICHED_ROWS = 500
TURNSTILE_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_EXPECTED_ACTION = "public_bom_audit"
# Carried on the OTP email_redirect_to and confirmation handoff (selector only).
STRESS_REPORT_ID_QUERY_PARAM = "cadivor_stress_report_id"


class StressTestError(ValueError):
    """An actionable validation or availability error for the public funnel."""


def normalize_stress_report_id(value: Any) -> str | None:
    """Accept only UUID-shaped report ids for redirect/query selectors."""
    text = str(value or "").strip()
    if not text or len(text) > 64:
        return None
    try:
        import uuid

        return str(uuid.UUID(text))
    except (TypeError, ValueError, AttributeError):
        return None


def daily_enriched_row_limit() -> int:
    raw = str(get_secret("CADIVOR_PUBLIC_BOM_DAILY_ENRICHED_ROWS") or "").strip()
    if not raw:
        return DEFAULT_DAILY_ENRICHED_ROWS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_DAILY_ENRICHED_ROWS


def turnstile_secret() -> str:
    return str(get_secret("CADIVOR_TURNSTILE_SECRET_KEY") or "").strip()


def turnstile_enabled() -> bool:
    """Turnstile is on whenever the server secret is configured (fail closed)."""
    return bool(turnstile_secret())


def turnstile_expected_hostnames() -> set[str]:
    raw = str(get_secret("CADIVOR_TURNSTILE_EXPECTED_HOSTNAMES") or "").strip()
    if not raw:
        return {"app.cadivor.com", "www.cadivor.com", "localhost", "127.0.0.1"}
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def qa_emails_allowlist() -> set[str]:
    """Server-only allowlist. Never populated from request body/query/frontend."""
    raw = str(get_secret("CADIVOR_PUBLIC_BOM_QA_EMAILS") or "").strip()
    if not raw:
        return set()
    emails: set[str] = set()
    for part in raw.split(","):
        candidate = part.strip().lower()
        if candidate and "@" in candidate:
            emails.add(candidate)
    return emails


def enabled() -> bool:
    """Fail closed until the signed ingress and service-role DB migration exist."""
    return (
        str(get_secret("CADIVOR_PUBLIC_BOM_STRESS_TEST_ENABLED") or "").lower()
        in {"1", "true", "yes"}
        and len(str(get_secret("CADIVOR_PUBLIC_BOM_HMAC_SECRET") or "")) >= 32
        and bool(get_secret("SUPABASE_SERVICE_ROLE_KEY"))
    )


def visitor_hash(signed_header: str, *, now: int | None = None, secret: str | None = None) -> str:
    """Accept only the fresh identity signed by Cadivor's trusted ingress Worker.

    Streamlit's `st.context.ip_address` and browser-supplied forwarding headers
    can be spoofed. The Worker must overwrite this header on every HTTP/WS request.
    """
    key = secret if secret is not None else str(get_secret("CADIVOR_PUBLIC_BOM_HMAC_SECRET") or "")
    if len(key) < 32:
        raise StressTestError("The public audit is temporarily unavailable.")
    try:
        version, stamp, ip, signature = str(signed_header).split(";", 3)
        timestamp = int(stamp)
        canonical_ip = str(ipaddress.ip_address(ip))
    except (ValueError, TypeError):
        raise StressTestError("The public audit is unavailable on this connection.") from None
    if version != "v1" or abs((now or int(time.time())) - timestamp) > 7200:
        raise StressTestError("The public audit connection expired. Refresh and try again.")
    expected = hmac.new(key.encode(), f"v1|{stamp}|{ip}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise StressTestError("The public audit is unavailable on this connection.")
    return hmac.new(key.encode(), f"ip|{canonical_ip}".encode(), hashlib.sha256).hexdigest()


def normalize_email_address(value: str) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", email):
        raise StressTestError("Enter a valid email address.")
    return email


def lead_source_from_query(query_params: Any) -> str:
    """Keep bounded, non-PII campaign attribution on the minimal lead record."""
    fields = []
    for key in ("utm_source", "utm_medium", "utm_campaign"):
        raw_value = str(query_params.get(key, "") or "").strip()
        value = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_value).strip("-.")[:48]
        if value:
            fields.append(value)
    return "utm:" + ":".join(fields) if fields else "homepage_stress_test"


def parse_bom(filename: str, payload: bytes) -> list[dict[str, Any]]:
    """Bound the public parser before spending distributor credits."""
    suffix = str(filename or "").lower().rsplit(".", 1)[-1]
    if suffix not in {"csv", "xlsx"} or not payload or len(payload) > MAX_BYTES:
        raise StressTestError("Upload a CSV or XLSX BOM smaller than 1 MB.")
    try:
        if suffix == "xlsx":
            with zipfile.ZipFile(io.BytesIO(payload)) as workbook:
                entries = workbook.infolist()
                if (len(entries) > 100 or
                        sum(entry.file_size for entry in entries) > MAX_XLSX_UNCOMPRESSED):
                    raise StressTestError("This workbook is too large for a public audit.")
            frame = pd.read_excel(io.BytesIO(payload), nrows=MAX_ROWS + 1, dtype=str, engine="openpyxl")
        else:
            frame = pd.read_csv(io.BytesIO(payload), nrows=MAX_ROWS + 1, dtype=str, encoding="utf-8-sig")
    except StressTestError:
        raise
    except Exception:
        raise StressTestError("Could not read this BOM. Use a valid CSV or XLSX file.") from None
    if frame.empty or len(frame) > MAX_ROWS:
        raise StressTestError(f"This public audit accepts 1–{MAX_ROWS} components. Create an account for larger BOMs.")
    aliases = {
        "mpn": "mpn", "part number": "mpn", "part_number": "mpn",
        "manufacturer part number": "mpn", "manufacturer_part_number": "mpn",
        "mfr part number": "mpn", "mfr_part_number": "mpn",
        "qty": "quantity", "quantity": "quantity",
        "manufacturer": "manufacturer", "mfr": "manufacturer", "mfg": "manufacturer",
    }
    columns = {column: aliases.get(str(column).strip().lower().replace("_", " "), str(column).strip().lower()) for column in frame.columns}
    frame = frame.rename(columns=columns)
    if "mpn" not in frame.columns or "quantity" not in frame.columns or frame.columns.duplicated().any():
        raise StressTestError("Include one manufacturer part number (MPN) and one quantity column.")
    rows = []
    has_manufacturer_column = "manufacturer" in frame.columns
    for _, row in frame.iterrows():
        mpn = str(row["mpn"] or "").strip()
        if (not mpn or mpn.lower() == "nan" or
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,79}", mpn) or
                not normalize_part_number(mpn)):
            raise StressTestError("Every row needs an MPN of 80 characters or fewer.")
        try:
            quantity = int(str(row["quantity"]).strip())
        except (ValueError, TypeError):
            raise StressTestError("Every row needs a whole-number quantity.") from None
        if quantity < 1 or quantity > 1_000_000:
            raise StressTestError("Every row needs a quantity between 1 and 1,000,000.")
        parsed = {"mpn": mpn, "quantity": quantity}
        if has_manufacturer_column:
            manufacturer = str(row.get("manufacturer", "") or "").strip()
            parsed["manufacturer"] = "" if manufacturer.lower() == "nan" else manufacturer
        rows.append(parsed)
    return rows


@lru_cache(maxsize=1)
def _service_client():
    from supabase import create_client

    url = get_secret("SUPABASE_URL", required=True)
    key = get_secret("SUPABASE_SERVICE_ROLE_KEY", required=True)
    return create_client(url, key)


def validate_turnstile(
    token: str | None,
    *,
    remoteip: str | None = None,
    expected_action: str = TURNSTILE_EXPECTED_ACTION,
) -> None:
    """Server-side Cloudflare Siteverify. Fail closed when Turnstile is enabled."""
    if not turnstile_enabled():
        return
    secret = turnstile_secret()
    value = str(token or "").strip()
    if not value:
        raise StressTestError("Complete the security check and try again.")
    try:
        import urllib.parse
        import urllib.request

        payload = urllib.parse.urlencode(
            {
                "secret": secret,
                "response": value,
                **({"remoteip": remoteip} if remoteip else {}),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            TURNSTILE_SITEVERIFY_URL,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
        import json

        result = json.loads(body) if body else {}
    except Exception:
        raise StressTestError("The security check could not be verified. Please try again.") from None
    if not result.get("success"):
        raise StressTestError("The security check failed. Refresh and try again.")
    hostname = str(result.get("hostname") or "").strip().lower()
    if hostname not in turnstile_expected_hostnames():
        raise StressTestError("The security check failed. Refresh and try again.")
    action = str(result.get("action") or "").strip()
    # Missing action must fail closed — require an exact match when expected.
    if not expected_action or action != expected_action:
        raise StressTestError("The security check failed. Refresh and try again.")


def resolve_qa_session(access_token: str | None) -> dict[str, Any] | None:
    """Return confirmed allowlisted user info from a bearer token, else None.

    Never trusts client-supplied email, QA flags, or report ownership claims.
    """
    token = str(access_token or "").strip()
    allowlist = qa_emails_allowlist()
    if not token or not allowlist:
        return None
    try:
        from supabase import create_client

        auth = create_client(
            get_secret("SUPABASE_URL", required=True),
            get_secret("SUPABASE_KEY", required=True),
        )
        user = auth.auth.get_user(token).user
        if not user or not getattr(user, "email_confirmed_at", None):
            return None
        email = normalize_email_address(getattr(user, "email", "") or "")
        if email not in allowlist:
            return None
        return {
            "email": email,
            "user_id": str(getattr(user, "id", "") or ""),
            "qa_mode": True,
        }
    except StressTestError:
        return None
    except Exception:
        return None


def _confirmed_session_email(access_token: str) -> str | None:
    token = str(access_token or "").strip()
    if not token:
        return None
    try:
        from supabase import create_client

        auth = create_client(
            get_secret("SUPABASE_URL", required=True),
            get_secret("SUPABASE_KEY", required=True),
        )
        user = auth.auth.get_user(token).user
        if not user or not getattr(user, "email_confirmed_at", None):
            return None
        return normalize_email_address(getattr(user, "email", "") or "")
    except Exception:
        return None


def _reserve(ip_hash: str, *, qa_mode: bool = False) -> str:
    rpc_name = (
        "cadivor_reserve_public_bom_stress_test_qa"
        if qa_mode
        else "cadivor_reserve_public_bom_stress_test"
    )
    try:
        response = _service_client().rpc(rpc_name, {"p_ip_hash": ip_hash}).execute()
    except Exception as exc:
        if "PUBLIC_BOM_DAILY_LIMIT" in str(exc):
            raise StressTestError(PUBLIC_BOM_LIMIT_MESSAGE) from None
        raise StressTestError("The audit is temporarily unavailable. Please try later.") from None
    report_id = str(response.data or "").strip().strip('"')
    if not report_id:
        raise StressTestError("The audit is temporarily unavailable. Please try later.")
    return report_id


def _claim_enrichment_budget(rows: int) -> None:
    needed = max(0, int(rows))
    if needed == 0:
        return
    limit = daily_enriched_row_limit()
    try:
        response = (
            _service_client()
            .rpc(
                "cadivor_claim_public_bom_enrichment_budget",
                {"p_rows": needed, "p_limit": limit},
            )
            .execute()
        )
        claimed = response.data
        if isinstance(claimed, list):
            claimed = claimed[0] if claimed else False
        if claimed is not True:
            raise StressTestError(PUBLIC_BOM_BUDGET_MESSAGE)
    except StressTestError:
        raise
    except Exception:
        raise StressTestError("The audit is temporarily unavailable. Please try later.") from None


def _pending_stub(row: dict[str, Any]) -> dict[str, Any]:
    """Unevaluated row stored until post-confirm completion (no supplier spend)."""
    return {
        "mpn": row["mpn"],
        "quantity": row["quantity"],
        "manufacturer": str(row.get("manufacturer") or ""),
        "matched_mpn": "",
        "description": "",
        "lifecycle": "Pending",
        "stock": None,
        "stock_sources": [],
        "stock_data_complete": False,
        "stock_evidence": "Not checked until email confirmation",
        "lead_time_weeks": None,
        "lead_time_source": "",
        "supplier_count": None,
        "sources": "",
        "supplier_coverage": "Supplier lookup deferred until email confirmation",
        "lifecycle_evidence": [],
        "lifecycle_evidence_summary": "",
        "lifecycle_conflict": False,
        "checked_at": "",
        "alternate_search_status": "Not checked in the free audit",
        "risk_reasons": [],
        "risk": "Pending",
        "verified": False,
        "enrichment_pending": True,
    }


def _enrich_failure_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "mpn": row["mpn"],
        "quantity": row["quantity"],
        "lifecycle": "Unverified",
        "stock": None,
        "lead_time_weeks": None,
        "supplier_count": None,
        "sources": "",
        "risk": "Needs verification",
        "stock_sources": [],
        "stock_data_complete": False,
        "stock_evidence": "Not reported by matched suppliers",
        "lead_time_source": "",
        "lifecycle_evidence": [],
        "lifecycle_evidence_summary": "",
        "supplier_coverage": "Supplier data could not be verified during this analysis",
        "lifecycle_conflict": False,
        "checked_at": "",
        "alternate_search_status": "Not checked in the free audit",
        "risk_reasons": [],
        "verified": False,
        "enrichment_pending": False,
    }


def _enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    results: list[dict[str, Any] | None] = [None] * len(rows)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_enrich_one, i, row): i for i, row in enumerate(rows)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                _, payload = future.result()
                payload["enrichment_pending"] = False
                results[index] = payload
            except Exception:
                results[index] = _enrich_failure_row(rows[index])
    return [row for row in results if row is not None]


def _enrich_one(index: int, row: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from integrations.supplier_aggregator import get_best_part_data
    from src.risk_engine import calculate_risk

    # Pass the BOM manufacturer so aggregator identity matching can reject
    # conflicting or unverifiable supplier brands instead of verifying the wrong hit.
    part = get_best_part_data(row["mpn"], str(row.get("manufacturer") or ""))
    verified = bool(part.get("supplier_data_verified"))
    try:
        lead_time = float(part.get("lead_time_weeks")) if verified else None
        if lead_time is not None and not math.isfinite(lead_time):
            lead_time = None
    except (TypeError, ValueError):
        lead_time = None
    try:
        supplier_count = int(part.get("supplier_count")) if verified and part.get("supplier_count") is not None else None
    except (TypeError, ValueError):
        supplier_count = None
    raw_stock = part.get("total_market_stock")
    if raw_stock in (None, ""):
        raw_stock = part.get("stock_total")
    stock = parse_stock_total(raw_stock) if verified else None
    risk = calculate_risk({
        **part, "quantity": row["quantity"], "stock_total": stock,
        "supplier_count": supplier_count, "lead_time_weeks": lead_time,
    }) if verified else {}
    return index, {
        "mpn": row["mpn"], "quantity": row["quantity"],
        "manufacturer": str(part.get("manufacturer") or "") if verified else "",
        "matched_mpn": str(part.get("manufacturer_part_number") or "") if verified else "",
        "description": str(part.get("description") or "") if verified else "",
        "lifecycle": str(part.get("lifecycle_status") or "Unknown") if verified else "Unverified",
        "stock": stock,
        "stock_sources": list(part.get("stock_data_sources") or []) if verified else [],
        "stock_data_complete": bool(part.get("stock_data_complete")) if verified else False,
        "stock_evidence": stock_evidence_note(
            stock,
            part.get("stock_data_sources") or [],
            complete=bool(part.get("stock_data_complete")),
            matching_supplier_count=supplier_count,
        ) if verified else "Not reported by matched suppliers",
        "lead_time_weeks": lead_time,
        "lead_time_source": str(part.get("lead_time_source") or part.get("source") or "") if verified and lead_time is not None else "",
        "supplier_count": supplier_count,
        "sources": str(part.get("sources_available") or part.get("source") or "")[:100] if verified else "",
        "supplier_coverage": str(
            (part.get("provider_health") or {}).get("summary_message")
            or "Supplier data could not be verified during this analysis"
        ) if verified else "Supplier data could not be verified during this analysis",
        "lifecycle_evidence": list(part.get("lifecycle_evidence") or []) if verified else [],
        "lifecycle_evidence_summary": "; ".join(
            f"{evidence.get('source')}: {evidence.get('status')}"
            for evidence in (part.get("lifecycle_evidence") or [])
            if isinstance(evidence, dict)
        ) if verified else "",
        "lifecycle_conflict": bool(part.get("lifecycle_conflict")) if verified else False,
        "checked_at": str(part.get("retrieved_at") or "") if verified else "",
        "risk": str(risk.get("risk_level") or "Needs verification"),
        "alternate_search_status": "Not checked in the free audit",
        "risk_reasons": [str(reason) for reason in (risk.get("risk_reasons") or [])],
        "verified": verified,
    }


def run_audit(
    filename: str,
    payload: bytes,
    signed_header: str,
    *,
    turnstile_token: str | None = None,
    access_token: str | None = None,
    remoteip: str | None = None,
) -> dict[str, Any]:
    """Anonymous preview: supplier lookups only for the first PREVIEW_ROWS.

    IP 2/24h reserve and Turnstile apply unless a server-verified QA session
    (confirmed allowlisted bearer) is present. Global daily enrichment budget
    always applies. Remaining rows are pending stubs until ``complete_audit``.
    """
    if not enabled():
        raise StressTestError("The public audit is temporarily unavailable.")
    qa = resolve_qa_session(access_token)
    qa_mode = bool(qa)
    if not qa_mode:
        validate_turnstile(turnstile_token, remoteip=remoteip)
    ip_hash = visitor_hash(signed_header)
    rows = parse_bom(filename, payload)
    # Atomic rate gate BEFORE any supplier lookup (QA skips the IP count only).
    report_id = _reserve(ip_hash, qa_mode=qa_mode)
    preview_n = min(PREVIEW_ROWS, len(rows))
    _claim_enrichment_budget(preview_n)
    preview_rows = rows[:preview_n]
    pending_rows = rows[preview_n:]
    enriched_preview = _enrich_rows(preview_rows)
    stubs = [_pending_stub(row) for row in pending_rows]
    results = enriched_preview + stubs
    try:
        update = {
            "filename": str(filename)[:180],
            "row_count": len(rows),
            "results": results,
            "status": "ready",
            "preview_enriched_count": preview_n,
            "qa_mode": qa_mode,
        }
        _service_client().table("cadivor_public_bom_stress_tests").update(update).eq(
            "id", report_id
        ).execute()
    except Exception:
        raise StressTestError("The audit could not be saved. Please try later.") from None
    if qa_mode:
        logging_note = {"event": "public_bom_qa_audit", "report_id": report_id}
        try:
            import logging

            logging.info("public_bom_qa_audit %s", logging_note)
        except Exception:
            pass
    remaining_count = len(stubs)
    return {
        "id": report_id,
        "row_count": len(rows),
        "preview": enriched_preview,
        "remaining_count": remaining_count,
        # Unevaluated rows have no supplier risk yet — do not invent High counts.
        "remaining_high_risk": 0,
        "remaining_unverified": remaining_count,
        "remaining_pending": remaining_count,
        "preview_enriched_count": preview_n,
        "qa_mode": qa_mode,
        "full_enriched": False,
    }


def _claim_full_enrichment(
    email: str,
    report_id: str,
    *,
    bypass_email_quota: bool = False,
    lease_seconds: int = FULL_ENRICHMENT_LEASE_SECONDS,
) -> str:
    try:
        response = (
            _service_client()
            .rpc(
                "cadivor_claim_public_bom_full_enrichment",
                {
                    "p_work_email": email,
                    "p_report_id": report_id,
                    "p_window_days": FULL_ENRICHMENT_WINDOW_DAYS,
                    "p_bypass_email_quota": bool(bypass_email_quota),
                    "p_lease_seconds": int(max(60, lease_seconds)),
                },
            )
            .execute()
        )
        status = response.data
        if isinstance(status, list):
            status = status[0] if status else ""
        return str(status or "")
    except Exception:
        raise StressTestError("The audit is temporarily unavailable. Please try later.") from None


def _load_owned_lead_report(
    email: str, report_id: str | None
) -> dict[str, Any] | None:
    selected_id = normalize_stress_report_id(report_id)
    query = (
        _service_client()
        .table("cadivor_public_bom_stress_tests")
        .select(
            "id,filename,row_count,results,created_at,status,work_email,"
            "full_enriched_at,qa_mode,preview_enriched_count,"
            "full_enrichment_lease_expires_at"
        )
        .eq("work_email", email)
        .eq("status", "lead_captured")
    )
    if selected_id:
        query = query.eq("id", selected_id).limit(1)
    else:
        query = query.order("created_at", desc=True).limit(1)
    rows = query.execute().data or []
    return rows[0] if rows else None


def _completed_report_payload(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(report["id"]),
        "filename": report.get("filename"),
        "row_count": report.get("row_count"),
        "results": list(report.get("results") or []),
        "created_at": report.get("created_at"),
        "full_enriched": True,
        "qa_mode": bool(report.get("qa_mode")),
    }


def complete_audit(
    access_token: str,
    report_id: str | None = None,
) -> dict[str, Any]:
    """Enrich pending stubs after confirmed email ownership. Idempotent.

    Enforces one full supplier-backed free audit per confirmed email / 30 days
    across completed and active in-progress leases (QA allowlist bypasses email
    quota only). Global daily budget still applies.
    """
    if not enabled():
        raise StressTestError("The public audit is temporarily unavailable.")
    email = _confirmed_session_email(access_token)
    if not email:
        raise StressTestError("Confirm your email and sign in to finish this audit.")
    qa = resolve_qa_session(access_token)
    try:
        report = _load_owned_lead_report(email, report_id)
    except Exception:
        raise StressTestError("Verified public audit not found.") from None
    if not report:
        raise StressTestError("Verified public audit not found.")
    owned_id = str(report["id"])
    claim = _claim_full_enrichment(
        email,
        owned_id,
        bypass_email_quota=bool(qa) or bool(report.get("qa_mode")),
    )
    if claim == "quota_exceeded":
        raise StressTestError(PUBLIC_BOM_EMAIL_QUOTA_MESSAGE)
    if claim == "not_found":
        raise StressTestError("Verified public audit not found.")
    if claim == "already_complete" or report.get("full_enriched_at"):
        return _completed_report_payload(report)
    if claim == "in_progress":
        # Another worker holds the lease for this report — do not start duplicate
        # supplier lookups. Reload once in case completion just landed.
        try:
            refreshed = _load_owned_lead_report(email, owned_id)
        except Exception:
            refreshed = None
        if refreshed and refreshed.get("full_enriched_at"):
            return _completed_report_payload(refreshed)
        raise StressTestError(PUBLIC_BOM_COMPLETE_IN_PROGRESS_MESSAGE)
    if claim != "claimed":
        raise StressTestError("The audit is temporarily unavailable. Please try later.")
    results = list(report.get("results") or [])
    pending_indexes = [
        index
        for index, row in enumerate(results)
        if isinstance(row, dict) and row.get("enrichment_pending")
    ]
    if not pending_indexes:
        # Mark complete even if nothing pending (idempotent refresh path).
        try:
            _service_client().table("cadivor_public_bom_stress_tests").update(
                {
                    "full_enriched_at": datetime.now(timezone.utc).isoformat(),
                    "full_enrichment_lease_expires_at": None,
                }
            ).eq("id", owned_id).execute()
        except Exception:
            pass
        report["results"] = results
        report["full_enriched_at"] = True
        return _completed_report_payload(report)
    pending_inputs = []
    for index in pending_indexes:
        row = results[index]
        pending_inputs.append(
            {
                "mpn": row.get("mpn"),
                "quantity": row.get("quantity"),
                "manufacturer": row.get("manufacturer") or "",
            }
        )
    _claim_enrichment_budget(len(pending_inputs))
    enriched = _enrich_rows(pending_inputs)
    for offset, index in enumerate(pending_indexes):
        results[index] = enriched[offset]
    try:
        _service_client().table("cadivor_public_bom_stress_tests").update(
            {
                "results": results,
                "full_enriched_at": datetime.now(timezone.utc).isoformat(),
                "full_enrichment_lease_expires_at": None,
            }
        ).eq("id", owned_id).execute()
        _service_client().table("cadivor_public_bom_leads").update(
            {
                "high_risk_count": sum(
                    row.get("verified") and row.get("risk") == "High" for row in results
                ),
                "unverified_count": sum(not row.get("verified") for row in results),
            }
        ).eq("report_id", owned_id).execute()
    except Exception:
        raise StressTestError("The audit could not be saved. Please try later.") from None
    report["results"] = results
    report["full_enriched_at"] = True
    return _completed_report_payload(report)


def capture_lead(report_id: str, address: str, *, source: str = "homepage_stress_test") -> str:
    """Validate again on server and record only minimal sales metadata."""
    email = normalize_email_address(address)
    lead_source = re.sub(r"[^A-Za-z0-9:_.-]+", "-", str(source or "")).strip("-:.")[:160]
    if not lead_source:
        lead_source = "homepage_stress_test"
    try:
        report = (_service_client().table("cadivor_public_bom_stress_tests")
                  .select("id,row_count,status,work_email,results").eq("id", report_id).single().execute()).data
        if not report or report["status"] not in {"ready", "lead_captured"} or report.get("work_email") not in (None, email):
            raise StressTestError("This report is no longer available.")
        if report["status"] == "ready":
            response = _service_client().table("cadivor_public_bom_stress_tests").update({
                "work_email": email, "status": "lead_captured"
            }).eq("id", report_id).eq("status", "ready").select("id").execute()
            if not response.data:
                raise StressTestError("This report is no longer available.")
        checked = list(report.get("results") or [])
        _service_client().table("cadivor_public_bom_leads").upsert({
            "report_id": report_id, "work_email": email,
            "row_count": report["row_count"], "source": lead_source,
            "high_risk_count": sum(row.get("verified") and row.get("risk") == "High" for row in checked),
            "unverified_count": sum(not row.get("verified") for row in checked),
        }, on_conflict="report_id").execute()
    except StressTestError:
        raise
    except Exception:
        raise StressTestError("We could not save your request. Please try again.") from None
    return email


def claim_verification_send(
    report_id: str,
    address: str,
    *,
    now: datetime | None = None,
    cooldown_seconds: int = VERIFICATION_RESEND_COOLDOWN_SECONDS,
) -> bool:
    """Atomically claim a verification-email send slot for this report/email.

    Uses the Postgres ``cadivor_claim_public_bom_verification`` RPC so only one
    concurrent request wins during the cooldown window. Returns True only for
    the winning caller; losers must not call the mailer.

    ``now`` is accepted for test clocks but the durable claim timestamp is
    assigned inside the database transaction.
    """
    del now  # DB clock is authoritative for the atomic claim.
    email = normalize_email_address(address)
    try:
        response = (
            _service_client()
            .rpc(
                "cadivor_claim_public_bom_verification",
                {
                    "p_report_id": report_id,
                    "p_work_email": email,
                    "p_cooldown_seconds": int(max(0, cooldown_seconds)),
                },
            )
            .execute()
        )
        claimed = response.data
        if isinstance(claimed, list):
            claimed = claimed[0] if claimed else False
        return claimed is True
    except StressTestError:
        raise
    except Exception:
        raise StressTestError("We could not save your request. Please try again.") from None


def release_verification_claim(report_id: str, address: str) -> None:
    """Clear a claimed send slot after a mailer failure so the user can retry."""
    email = normalize_email_address(address)
    try:
        _service_client().table("cadivor_public_bom_leads").update({
            "verification_sent_at": None,
        }).eq("report_id", report_id).eq("work_email", email).execute()
    except Exception:
        return


def request_full_report(
    report_id: str,
    address: str,
    signed_header: str,
    *,
    source: str = "homepage_stress_test",
) -> tuple[str, bool]:
    """Validate visitor HMAC, capture the lead, and send at most one email per cooldown.

    Returns ``(email, verification_sent)``. Does not send real mail in tests when
    ``send_report_verification`` is mocked.
    """
    visitor_hash(signed_header)
    email = capture_lead(report_id, address, source=source)
    if not claim_verification_send(report_id, email):
        return email, False
    try:
        send_report_verification(email, report_id=report_id)
    except StressTestError:
        release_verification_claim(report_id, email)
        raise
    return email, True


def send_report_verification(address: str, *, report_id: str | None = None) -> None:
    """Provision/sign in by email link, using Cadivor's verified callback.

    The Supabase Magic Link email template must send TokenHash + type=email to
    `signup_confirmation_redirect_url()`; see the rollout document. No session
    is trusted until the existing callback verifies the token hash.

    ``report_id`` is appended as a selector only; Reports still authorizes via
    the confirmed session email before returning that BOM.
    """
    email = normalize_email_address(address)
    safe_report_id = normalize_stress_report_id(report_id)
    try:
        from supabase import create_client
        from src.auth_signup_confirmation import signup_confirmation_redirect_url
        from urllib.parse import urlencode

        redirect = signup_confirmation_redirect_url() + "&cadivor_stress_report=1"
        if safe_report_id:
            redirect += "&" + urlencode({STRESS_REPORT_ID_QUERY_PARAM: safe_report_id})
        auth = create_client(get_secret("SUPABASE_URL", required=True),
                             get_secret("SUPABASE_KEY", required=True))
        auth.auth.sign_in_with_otp({
            "email": email,
            "options": {
                "should_create_user": True,
                "email_redirect_to": redirect,
            },
        })
    except Exception:
        raise StressTestError("Could not send the verification link. Please try again later.") from None


def verified_report(access_token: str, *, report_id: str | None = None) -> dict[str, Any] | None:
    """Authorization is rechecked against Supabase Auth, not an email form value.

    ``report_id`` selects which owned lead-captured audit to open. Ownership is
    always the bearer session's confirmed email; a foreign id returns None.
    """
    if not enabled() or not access_token:
        return None
    try:
        from supabase import create_client

        auth = create_client(get_secret("SUPABASE_URL", required=True), get_secret("SUPABASE_KEY", required=True))
        user = auth.auth.get_user(access_token).user
        if not user or not getattr(user, "email_confirmed_at", None):
            return None
        email = normalize_email_address(getattr(user, "email", ""))
        if not email:
            return None
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        selected_id = normalize_stress_report_id(report_id)
        query = (
            _service_client()
            .table("cadivor_public_bom_stress_tests")
            .select(
                "id,filename,row_count,results,created_at,full_enriched_at,"
                "qa_mode,preview_enriched_count"
            )
            .eq("work_email", email)
            .eq("status", "lead_captured")
            .gte("created_at", cutoff)
        )
        if selected_id:
            # Selector only — still constrained by work_email above.
            query = query.eq("id", selected_id).limit(1)
        else:
            query = query.order("created_at", desc=True).limit(1)
        rows = query.execute().data or []
        if not rows:
            return None
        report = rows[0]
        report["full_enriched"] = bool(report.get("full_enriched_at"))
        report["qa_mode"] = bool(report.get("qa_mode"))
        return report
    except Exception:
        return None


def export_verified_report(
    access_token: str,
    *,
    report_id: str | None = None,
    format: str = "csv",
) -> tuple[bytes, str, str]:
    """Return (body, media_type, filename) for an owned fully-enriched audit."""
    report = verified_report(access_token, report_id=report_id)
    if not report:
        raise StressTestError("Verified public audit not found.")
    results = list(report.get("results") or [])
    if any(isinstance(row, dict) and row.get("enrichment_pending") for row in results):
        raise StressTestError(
            "Finish supplier enrichment before downloading the complete audit."
        )
    fmt = str(format or "csv").strip().lower()
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", str(report.get("filename") or "bom-audit"))[
        :80
    ].strip("-.") or "bom-audit"
    if fmt == "xlsx":
        return (
            build_audit_xlsx(report),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"{base}-complete.xlsx",
        )
    return build_audit_csv(results), "text/csv; charset=utf-8", f"{base}-complete.csv"


def _safe_export_cell(value: Any) -> Any:
    """Keep supplier-provided text from becoming a formula in spreadsheet apps."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


AUDIT_EXPORT_COLUMNS = (
    "MPN", "Matched MPN", "Manufacturer", "Qty", "Lifecycle",
    "Lifecycle evidence", "Reported stock", "Stock evidence",
    "Lead time (weeks)", "Lead time source", "Matching suppliers",
    "Evidence sources", "Supplier coverage", "Cadivor checked at (UTC)",
    "Risk", "Why",
)


def _report_integer(value: Any) -> int | None:
    """Return whole-number report values without pandas' nullable-float suffix."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        if pd.isna(value):
            return None
        number = float(value)
        return int(number) if math.isfinite(number) and number.is_integer() else None
    except (TypeError, ValueError, OverflowError):
        return None


def _report_records(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the stable full-evidence schema used by both download formats."""
    records = []
    for row in results:
        records.append({
            "MPN": str(row.get("mpn") or ""),
            "Matched MPN": str(row.get("matched_mpn") or ""),
            "Manufacturer": str(row.get("manufacturer") or ""),
            "Qty": _report_integer(row.get("quantity")),
            "Lifecycle": str(row.get("lifecycle") or "Unverified"),
            "Lifecycle evidence": str(row.get("lifecycle_evidence_summary") or "Not reported"),
            "Reported stock": _report_integer(row.get("stock")),
            "Stock evidence": str(row.get("stock_evidence") or "Not reported by matched suppliers"),
            "Lead time (weeks)": row.get("lead_time_weeks"),
            "Lead time source": str(row.get("lead_time_source") or "Not reported"),
            "Matching suppliers": _report_integer(row.get("supplier_count")),
            "Evidence sources": str(row.get("sources") or ""),
            "Supplier coverage": str(row.get("supplier_coverage") or "Not reported"),
            "Cadivor checked at (UTC)": str(row.get("checked_at") or ""),
            "Risk": str(row.get("risk") or "Needs verification"),
            "Why": _risk_reason_text(row.get("risk_reasons"))
            or "No risk score: evidence needs verification",
        })
    return records


def _risk_reason_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(reason).strip() for reason in value if str(reason).strip())
    return ""


def build_audit_csv(results: list[dict[str, Any]]) -> bytes:
    """Create a spreadsheet-friendly CSV with stable integer and blank fields."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=AUDIT_EXPORT_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for record in _report_records(results):
        writer.writerow({key: _safe_export_cell(record.get(key)) for key in AUDIT_EXPORT_COLUMNS})
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def build_audit_xlsx(report: dict[str, Any]) -> bytes:
    """Create a readable workbook with an overview and complete evidence sheet."""
    from datetime import datetime
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.table import Table, TableStyleInfo
    from openpyxl.utils import get_column_letter

    records = _report_records(list(report.get("results") or []))
    navy, blue, pale_blue = "10284B", "255FF2", "EDF4FF"
    light_border = Side(style="thin", color="D9E4F3")
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Summary"
    summary.sheet_view.showGridLines = False
    summary.merge_cells("A1:J1")
    summary["A1"] = "Cadivor | BOM Stress Test"
    summary["A1"].font = Font(name="Aptos Display", size=20, bold=True, color="FFFFFF")
    summary["A1"].fill = PatternFill("solid", fgColor=navy)
    summary["A1"].alignment = Alignment(vertical="center")
    summary.row_dimensions[1].height = 36
    summary.merge_cells("A2:J2")
    summary["A2"] = _safe_export_cell(f"File: {report.get('filename') or 'Uploaded BOM'}")
    summary["A2"].font = Font(name="Aptos", size=11, color=navy, bold=True)

    generated = str(report.get("created_at") or "").strip()
    summary.merge_cells("A3:J3")
    summary["A3"] = f"Audit created (UTC): {generated or 'timestamp not available'}"
    summary["A3"].font = Font(name="Aptos", size=10, color="526783")

    risks = [str(row.get("Risk") or "Needs verification").strip().lower() for row in records]
    metrics = [
        ("Components", len(records)),
        ("High risk", sum(value == "high" for value in risks)),
        ("Medium risk", sum(value == "medium" for value in risks)),
        ("Low risk", sum(value == "low" for value in risks)),
        ("Needs verification", sum(value == "needs verification" for value in risks)),
    ]
    for index, (label, value) in enumerate(metrics):
        start_col = 1 + index * 2
        end_col = start_col + 1
        summary.merge_cells(start_row=5, start_column=start_col, end_row=5, end_column=end_col)
        summary.merge_cells(start_row=6, start_column=start_col, end_row=6, end_column=end_col)
        label_cell = summary.cell(5, start_col, label)
        value_cell = summary.cell(6, start_col, value)
        label_cell.font = Font(name="Aptos", size=10, bold=True, color="526783")
        value_cell.font = Font(name="Aptos Display", size=18, bold=True, color=navy)
        for row_index in (5, 6):
            for col_index in range(start_col, end_col + 1):
                cell = summary.cell(row_index, col_index)
                cell.fill = PatternFill("solid", fgColor=pale_blue)
                cell.border = Border(bottom=light_border)
                cell.alignment = Alignment(horizontal="center", vertical="center")

    summary.merge_cells("A8:J8")
    summary["A8"] = (
        "This report reflects supplier data returned at the time shown. Blank inventory or lead-time values "
        "mean no usable value was reported. Verify current availability and engineering fit with the source before release."
    )
    summary["A8"].font = Font(name="Aptos", size=10, color="526783", italic=True)
    summary["A8"].alignment = Alignment(wrap_text=True, vertical="center")
    summary.row_dimensions[8].height = 34
    summary.merge_cells("A10:D10")
    summary["A10"] = "Component overview"
    summary["A10"].font = Font(name="Aptos Display", size=13, bold=True, color=navy)
    overview_headers = ["BOM MPN", "Qty", "Lifecycle", "Risk"]
    for col_index, label in enumerate(overview_headers, start=1):
        cell = summary.cell(11, col_index, label)
        cell.font = Font(name="Aptos", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=blue)
        cell.alignment = Alignment(vertical="center")
    risk_fills = {
        "high": "FDECEC", "medium": "FFF4DC", "low": "EAF7EF",
        "needs verification": "EEF1F5",
    }
    for row_index, record in enumerate(records, start=12):
        values = [record["MPN"], record["Qty"], record["Lifecycle"], record["Risk"]]
        for col_index, value in enumerate(values, start=1):
            cell = summary.cell(row_index, col_index, _safe_export_cell(value))
            cell.font = Font(name="Aptos", size=10, color=navy)
            cell.alignment = Alignment(vertical="top")
            cell.border = Border(bottom=light_border)
        risk_cell = summary.cell(row_index, 4)
        risk_cell.fill = PatternFill("solid", fgColor=risk_fills.get(str(record["Risk"]).lower(), "FFFFFF"))
        risk_cell.font = Font(name="Aptos", size=10, bold=True, color=navy)
    if records:
        table = Table(displayName="BOMComponentOverview", ref=f"A11:D{11 + len(records)}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True,
                                               showColumnStripes=False, showFirstColumn=False,
                                               showLastColumn=False)
        summary.add_table(table)
    for column, width in {"A": 28, "B": 12, "C": 30, "D": 24}.items():
        summary.column_dimensions[column].width = width
    summary.freeze_panes = "A12"

    detail = workbook.create_sheet("Component evidence")
    detail.sheet_view.showGridLines = False
    detail.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(AUDIT_EXPORT_COLUMNS))
    detail.cell(1, 1, "Complete supplier and lifecycle evidence")
    detail.cell(1, 1).font = Font(name="Aptos Display", size=16, bold=True, color="FFFFFF")
    detail.cell(1, 1).fill = PatternFill("solid", fgColor=navy)
    detail.cell(1, 1).alignment = Alignment(vertical="center")
    detail.row_dimensions[1].height = 30
    detail.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(AUDIT_EXPORT_COLUMNS))
    detail.cell(2, 1, "Blank values indicate the supplier did not report a usable value; they do not mean zero or active.")
    detail.cell(2, 1).font = Font(name="Aptos", size=10, color="526783", italic=True)
    header_row = 4
    for col_index, label in enumerate(AUDIT_EXPORT_COLUMNS, start=1):
        cell = detail.cell(header_row, col_index, label)
        cell.font = Font(name="Aptos", bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=blue)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    detail.row_dimensions[header_row].height = 30
    for row_index, record in enumerate(records, start=header_row + 1):
        for col_index, label in enumerate(AUDIT_EXPORT_COLUMNS, start=1):
            value = record.get(label)
            if label == "Cadivor checked at (UTC)" and value:
                try:
                    value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    value = value.astimezone(timezone.utc).replace(tzinfo=None)
                except (ValueError, OverflowError):
                    pass
            cell = detail.cell(row_index, col_index, _safe_export_cell(value))
            cell.font = Font(name="Aptos", size=10, color=navy)
            cell.alignment = Alignment(vertical="top", wrap_text=label in {
                "Lifecycle evidence", "Stock evidence", "Supplier coverage", "Why"
            })
            cell.border = Border(bottom=light_border)
            if label == "Cadivor checked at (UTC)" and isinstance(value, datetime):
                cell.number_format = "yyyy-mm-dd hh:mm:ss"
            if label in {"Qty", "Reported stock", "Matching suppliers"} and value is not None:
                cell.number_format = "#,##0"
            if label == "Lead time (weeks)" and value is not None:
                cell.number_format = "0.0"
            if label == "Risk":
                cell.fill = PatternFill("solid", fgColor=risk_fills.get(str(value).lower(), "FFFFFF"))
                cell.font = Font(name="Aptos", size=10, bold=True, color=navy)
    if records:
        table = Table(displayName="BOMComponentEvidence",
                      ref=f"A{header_row}:{get_column_letter(len(AUDIT_EXPORT_COLUMNS))}{header_row + len(records)}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True,
                                               showColumnStripes=False, showFirstColumn=False,
                                               showLastColumn=False)
        detail.add_table(table)
    widths = [22, 22, 30, 12, 24, 52, 18, 48, 18, 24, 18, 32, 60, 28, 22, 72]
    for index, width in enumerate(widths, start=1):
        detail.column_dimensions[get_column_letter(index)].width = width
    detail.freeze_panes = "A5"
    for row_index in range(header_row + 1, header_row + 1 + len(records)):
        detail.row_dimensions[row_index].height = 32

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def build_audit_preview(results: list[dict[str, Any]]) -> pd.DataFrame:
    """Keep the on-screen table focused; detailed evidence remains available per part."""
    frame = pd.DataFrame([{
        "BOM MPN": str(row.get("mpn") or ""),
        "Manufacturer": str(row.get("manufacturer") or "Not matched"),
        "Qty": _report_integer(row.get("quantity")),
        "Lifecycle": str(row.get("lifecycle") or "Unverified"),
        "Reported stock": _report_integer(row.get("stock")),
        "Lead time (weeks)": row.get("lead_time_weeks"),
        "Matching suppliers": _report_integer(row.get("supplier_count")),
        "Risk": str(row.get("risk") or "Needs verification"),
    } for row in results], columns=[
        "BOM MPN", "Manufacturer", "Qty", "Lifecycle", "Reported stock",
        "Lead time (weeks)", "Matching suppliers", "Risk",
    ])
    for column in ("Qty", "Reported stock", "Matching suppliers"):
        frame[column] = pd.array(frame[column], dtype="Int64")
    return frame


def render_verified_report(access_token: str) -> None:
    """Shown inside authenticated Reports, after rechecking the verified JWT."""
    import streamlit as st

    if not enabled():
        return
    user = st.session_state.get("user")
    user_id = str(getattr(user, "id", "") or (user.get("id") if isinstance(user, dict) else ""))
    cache = st.session_state.get("cadivor_stress_verified_report_cache") or {}
    if cache.get("user_id") != user_id or time.time() - cache.get("at", 0) > 120:
        cache = {"user_id": user_id, "at": time.time(), "report": verified_report(access_token)}
        st.session_state["cadivor_stress_verified_report_cache"] = cache
    report = cache.get("report")
    if not report:
        return
    st.markdown("### Your BOM stress test")
    st.caption("Full supplier and lifecycle results · available for seven days after upload")
    st.text(f"File: {str(report.get('filename') or 'Uploaded BOM')}")
    results = list(report.get("results") or [])
    if not results:
        st.info("This report has no verified component results yet.")
        return
    high_risk = sum(str(row.get("risk") or "").strip().lower() == "high" for row in results)
    needs_verification = sum(
        str(row.get("risk") or "").strip().lower() == "needs verification" for row in results
    )
    st.caption(
        f"{len(results)} components · {high_risk} high risk · "
        f"{needs_verification} need supplier verification"
    )
    preview = build_audit_preview(results)
    st.dataframe(
        preview,
        column_config={
            "BOM MPN": st.column_config.TextColumn("BOM MPN", width="medium"),
            "Manufacturer": st.column_config.TextColumn("Manufacturer", width="medium"),
            "Qty": st.column_config.NumberColumn("Qty", width="small", format="%d"),
            "Lifecycle": st.column_config.TextColumn("Lifecycle", width="medium"),
            "Reported stock": st.column_config.NumberColumn("Reported stock", width="medium", format="%d"),
            "Lead time (weeks)": st.column_config.NumberColumn("Lead time (weeks)", width="small", format="%.1f"),
            "Matching suppliers": st.column_config.NumberColumn("Suppliers", width="small", format="%d"),
            "Risk": st.column_config.TextColumn("Risk", width="small"),
        },
        hide_index=True,
        use_container_width=True,
        height=min(580, 38 * min(len(results), 14) + 42),
    )
    st.caption(
        "Stock, lifecycle, and lead time reflect the supplier sources checked at the recorded time. "
        "A blank value means no usable value was reported; it does not mean zero or active."
    )
    with st.expander("Review component evidence and risk rationale"):
        selected_index = st.selectbox(
            "Component",
            options=list(range(len(results))),
            format_func=lambda index: (
                f"{results[index].get('mpn') or 'Unknown MPN'} · "
                f"{results[index].get('risk') or 'Needs verification'}"
            ),
            key="cadivor_stress_evidence_component",
        )
        selected = results[selected_index]
        evidence_columns = st.columns(2)
        evidence_fields = [
            ("Matched MPN", selected.get("matched_mpn") or "Not matched"),
            ("Manufacturer", selected.get("manufacturer") or "Not reported"),
            ("Lifecycle evidence", selected.get("lifecycle_evidence_summary") or "Not reported"),
            ("Stock evidence", selected.get("stock_evidence") or "Not reported by matched suppliers"),
            ("Lead-time source", selected.get("lead_time_source") or "Not reported"),
            ("Evidence sources", selected.get("sources") or "Not reported"),
            ("Supplier coverage", selected.get("supplier_coverage") or "Not reported"),
            ("Checked at (UTC)", selected.get("checked_at") or "Not reported"),
            ("Why this risk was assigned", _risk_reason_text(selected.get("risk_reasons"))
             or "No risk score: evidence needs verification"),
        ]
        for index, (label, value) in enumerate(evidence_fields):
            with evidence_columns[index % 2]:
                st.markdown(f"**{label}**")
                st.text(str(value))
    with st.container(border=True):
        st.markdown("**Download the complete report**")
        download_columns = st.columns([1, 1, 2])
        with download_columns[0]:
            st.download_button(
                "Download Excel report",
                data=build_audit_xlsx(report),
                file_name="cadivor_bom_stress_test.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                key="cadivor_stress_report_xlsx",
                use_container_width=True,
            )
        with download_columns[1]:
            st.download_button(
                "Download CSV data",
                data=build_audit_csv(results),
                file_name="cadivor_bom_stress_test.csv",
                mime="text/csv",
                key="cadivor_stress_report_csv",
                use_container_width=True,
            )
        st.caption("Excel includes a summary and complete component evidence. CSV contains the same evidence fields for reuse.")
