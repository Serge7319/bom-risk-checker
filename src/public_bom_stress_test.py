"""Server-side anonymous BOM teaser. Never return locked component evidence to the browser."""

from __future__ import annotations

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

from src.normalizer import normalize_part_number
from src.secrets import get_secret

MAX_BYTES = 1_000_000
MAX_ROWS = 30
PREVIEW_ROWS = 5
MAX_XLSX_UNCOMPRESSED = 8_000_000
VISITOR_HEADER = "X-Cadivor-Visitor"
PUBLIC_BOM_LIMIT_MESSAGE = "This connection has used its two free BOM audits in the last 24 hours."
CONSUMER_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "ymail.com",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "aol.com", "icloud.com", "me.com", "mail.com", "proton.me",
    "protonmail.com", "gmx.com", "qq.com", "163.com", "126.com",
})


class StressTestError(ValueError):
    """An actionable validation or availability error for the public funnel."""


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


def work_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", email):
        raise StressTestError("Enter a valid work email address.")
    domain = email.rsplit("@", 1)[1]
    if domain in CONSUMER_DOMAINS or domain.endswith((".gmail.com", ".yahoo.com", ".outlook.com")):
        raise StressTestError("Use a work or institutional email address to unlock the report.")
    return email


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
    }
    columns = {column: aliases.get(str(column).strip().lower().replace("_", " "), str(column).strip().lower()) for column in frame.columns}
    frame = frame.rename(columns=columns)
    if "mpn" not in frame.columns or "quantity" not in frame.columns or frame.columns.duplicated().any():
        raise StressTestError("Include one manufacturer part number (MPN) and one quantity column.")
    rows = []
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
        rows.append({"mpn": mpn, "quantity": quantity})
    return rows


@lru_cache(maxsize=1)
def _service_client():
    from supabase import create_client

    url = get_secret("SUPABASE_URL", required=True)
    key = get_secret("SUPABASE_SERVICE_ROLE_KEY", required=True)
    return create_client(url, key)


def _reserve(ip_hash: str) -> str:
    try:
        response = _service_client().rpc(
            "cadivor_reserve_public_bom_stress_test", {"p_ip_hash": ip_hash}
        ).execute()
    except Exception as exc:
        if "PUBLIC_BOM_DAILY_LIMIT" in str(exc):
            raise StressTestError(PUBLIC_BOM_LIMIT_MESSAGE) from None
        raise StressTestError("The audit is temporarily unavailable. Please try later.") from None
    report_id = str(response.data or "").strip().strip('"')
    if not report_id:
        raise StressTestError("The audit is temporarily unavailable. Please try later.")
    return report_id


def _enrich_one(index: int, row: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    from integrations.supplier_aggregator import get_best_part_data
    from integrations.stock_coercion import coerce_stock_total
    from src.risk_engine import calculate_risk

    part = get_best_part_data(row["mpn"])
    verified = bool(part.get("supplier_data_verified"))
    try:
        lead_time = float(part.get("lead_time_weeks")) if verified else None
        if lead_time is not None and not math.isfinite(lead_time):
            lead_time = None
    except (TypeError, ValueError):
        lead_time = None
    try:
        supplier_count = int(part.get("supplier_count") or 0) if verified else None
    except (TypeError, ValueError):
        supplier_count = 0 if verified else None
    stock = coerce_stock_total(part.get("total_market_stock") or part.get("stock_total")) if verified else None
    risk = calculate_risk({
        **part, "quantity": row["quantity"], "stock_total": stock,
        "supplier_count": supplier_count, "lead_time_weeks": lead_time,
    }) if verified else {}
    return index, {
        "mpn": row["mpn"], "quantity": row["quantity"],
        "lifecycle": str(part.get("lifecycle_status") or "Unknown") if verified else "Unverified",
        "stock": stock,
        "lead_time_weeks": lead_time,
        "supplier_count": supplier_count,
        "sources": str(part.get("sources_available") or part.get("source") or "")[:100] if verified else "",
        "risk": str(risk.get("risk_level") or "Needs verification"),
        "risk_reasons": [str(reason) for reason in (risk.get("risk_reasons") or [])],
        "verified": verified,
    }


def run_audit(filename: str, payload: bytes, signed_header: str) -> dict[str, Any]:
    if not enabled():
        raise StressTestError("The public audit is temporarily unavailable.")
    ip_hash = visitor_hash(signed_header)
    rows = parse_bom(filename, payload)
    report_id = _reserve(ip_hash)  # Atomic 24h rate gate BEFORE any supplier lookup.
    results: list[dict[str, Any] | None] = [None] * len(rows)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_enrich_one, i, row): i for i, row in enumerate(rows)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                _, results[index] = future.result()
            except Exception:
                results[index] = {
                    "mpn": rows[index]["mpn"], "quantity": rows[index]["quantity"],
                    "lifecycle": "Unverified", "stock": None, "lead_time_weeks": None,
                    "supplier_count": None, "sources": "", "risk": "Needs verification",
                    "risk_reasons": [], "verified": False,
                }
    enriched = [row for row in results if row is not None]
    try:
        _service_client().table("cadivor_public_bom_stress_tests").update({
            "filename": str(filename)[:180], "row_count": len(rows), "results": enriched,
            "status": "ready",
        }).eq("id", report_id).execute()
    except Exception:
        raise StressTestError("The audit could not be saved. Please try later.") from None
    # Only the first five enriched records enter the Streamlit response/session.
    remaining = enriched[PREVIEW_ROWS:]
    return {
        "id": report_id,
        "row_count": len(rows),
        "preview": enriched[:PREVIEW_ROWS],
        "remaining_count": len(remaining),
        "remaining_high_risk": sum(row["risk"] == "High" for row in remaining),
        "remaining_unverified": sum(not row["verified"] for row in remaining),
    }


def capture_lead(report_id: str, address: str) -> str:
    """Validate again on server and record only minimal sales metadata."""
    email = work_email(address)
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
            "row_count": report["row_count"], "source": "homepage_stress_test",
            "high_risk_count": sum(row.get("verified") and row.get("risk") == "High" for row in checked),
            "unverified_count": sum(not row.get("verified") for row in checked),
        }, on_conflict="report_id").execute()
    except StressTestError:
        raise
    except Exception:
        raise StressTestError("We could not save your request. Please try again.") from None
    return email


def send_report_verification(address: str) -> None:
    """Provision/sign in by email link, using Cadivor's verified callback.

    The Supabase Magic Link email template must send TokenHash + type=email to
    `signup_confirmation_redirect_url()`; see the rollout document. No session
    is trusted until the existing callback verifies the token hash.
    """
    email = work_email(address)
    try:
        from supabase import create_client
        from src.auth_signup_confirmation import signup_confirmation_redirect_url

        auth = create_client(get_secret("SUPABASE_URL", required=True),
                             get_secret("SUPABASE_KEY", required=True))
        auth.auth.sign_in_with_otp({
            "email": email,
            "options": {
                "should_create_user": True,
                "email_redirect_to": signup_confirmation_redirect_url() + "&cadivor_stress_report=1",
            },
        })
    except Exception:
        raise StressTestError("Could not send the verification link. Please try again later.") from None


def verified_report(access_token: str, *, report_id: str | None = None) -> dict[str, Any] | None:
    """Authorization is rechecked against Supabase Auth, not an email form value."""
    if not enabled() or not access_token:
        return None
    try:
        from supabase import create_client

        auth = create_client(get_secret("SUPABASE_URL", required=True), get_secret("SUPABASE_KEY", required=True))
        user = auth.auth.get_user(access_token).user
        if not user or not getattr(user, "email_confirmed_at", None):
            return None
        email = work_email(getattr(user, "email", ""))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        query = (_service_client().table("cadivor_public_bom_stress_tests")
                 .select("id,filename,row_count,results,created_at")
                 .eq("work_email", email).eq("status", "lead_captured")
                 .gte("created_at", cutoff)
                 .order("created_at", desc=True).limit(1))
        if report_id:
            query = query.eq("id", report_id)
        rows = query.execute().data or []
        return rows[0] if rows else None
    except Exception:
        return None


def _safe_export_cell(value: Any) -> Any:
    """Keep supplier-provided text from becoming a formula in spreadsheet apps."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


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
    st.caption("Your complete supplier and lifecycle audit is available for seven days after upload. Confirm the evidence before an engineering release decision.")
    st.write(str(report.get("filename") or "Uploaded BOM"))
    results = list(report.get("results") or [])
    if not results:
        st.info("This report has no verified component results yet.")
        return
    display = pd.DataFrame([{
        "MPN": row.get("mpn"), "Qty": row.get("quantity"),
        "Lifecycle": row.get("lifecycle"),
        "Stock": row.get("stock"), "Lead time (weeks)": row.get("lead_time_weeks"),
        "Suppliers": row.get("supplier_count"), "Evidence source": row.get("sources"),
        "Risk": row.get("risk"),
        "Why": "; ".join(row.get("risk_reasons") or []) or "Supplier data needs verification",
    } for row in results])
    st.dataframe(display, hide_index=True, use_container_width=True)
    export = display.apply(lambda column: column.map(_safe_export_cell))
    st.download_button("Download audit CSV", export.to_csv(index=False).encode("utf-8-sig"),
                       file_name="cadivor_bom_stress_test.csv", mime="text/csv",
                       key="cadivor_stress_report_csv")
