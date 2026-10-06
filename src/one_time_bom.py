"""Server-only one-time BOM checkout and paid analysis credit.

Never use the checkout return URL as proof of payment. The Stripe webhook
verifies the payment and moves a private order to `paid` before use.
"""

from __future__ import annotations

from functools import lru_cache
from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.secrets import get_secret, get_secret_bool

MAX_PARTS = 100


class OneTimeBOMError(RuntimeError):
    pass


def enabled() -> bool:
    return (
        get_secret_bool("CADIVOR_ONE_TIME_BOM_REPORT_ENABLED")
        and bool(get_secret("STRIPE_ONE_TIME_BOM_REPORT_PRICE_ID"))
        and _orders_available()
    )


def _orders_available() -> bool:
    # Disabling new sales must not strand a customer who has already paid.
    # Before the migration, do not query a missing table on every BOM rerun.
    return (
        get_secret_bool("CADIVOR_ONE_TIME_BOM_ORDERS_READY")
        and bool(get_secret("SUPABASE_SERVICE_ROLE_KEY"))
    )


def purchase_history_available() -> bool:
    """A sales pause must not hide reports customers already purchased."""
    return _orders_available()


def purchase_history(user_id: str) -> list[dict]:
    """Read this account's private order history for Billing, without Stripe IDs."""
    if not _orders_available():
        return []
    try:
        rows = (_service_client().table("cadivor_one_time_bom_orders")
                .select("id,status,created_at,paid_at,analysis_id")
                .eq("user_id", _identity(user_id))
                .in_("status", ["pending", "paid", "reserved", "consumed", "refunded"])
                .order("created_at", desc=True).limit(10).execute()).data or []
        return rows
    except Exception:
        raise OneTimeBOMError("Your one-time report history is temporarily unavailable.") from None


@lru_cache(maxsize=1)
def _service_client():
    from supabase import create_client

    return create_client(
        get_secret("SUPABASE_URL", required=True),
        get_secret("SUPABASE_SERVICE_ROLE_KEY", required=True),
    )


def _identity(user_id: str) -> str:
    try:
        return str(UUID(str(user_id)))
    except (TypeError, ValueError):
        raise OneTimeBOMError("Sign in again to purchase a BOM report.") from None


@lru_cache(maxsize=2)
def price_label(price_id: str) -> str:
    """Show the actual configured Stripe amount before asking for payment."""
    import stripe
    from src.stripe_helper import _ensure_stripe_api_key

    try:
        _ensure_stripe_api_key()
        price = stripe.Price.retrieve(price_id)
        if (not price.active or price.recurring or price.currency != "usd"
                or not isinstance(price.unit_amount, int) or price.unit_amount <= 0):
            raise OneTimeBOMError("The one-time report price is not configured correctly.")
        return f"USD {price.unit_amount / 100:,.2f}"
    except OneTimeBOMError:
        raise
    except Exception:
        raise OneTimeBOMError("The report price is temporarily unavailable.") from None


def public_checkout_price() -> str | None:
    """Return a safe display price only when a new one-time checkout can start."""
    if not enabled():
        return None
    price_id = str(
        get_secret("STRIPE_ONE_TIME_BOM_REPORT_PRICE_ID", default="") or ""
    ).strip()
    if not price_id:
        return None
    try:
        return price_label(price_id)
    except OneTimeBOMError:
        return None


def available_credit(user_id: str) -> bool:
    if not _orders_available():
        return False
    try:
        rows = (_service_client().table("cadivor_one_time_bom_orders")
                .select("id").eq("user_id", _identity(user_id))
                .eq("status", "paid").limit(1).execute()).data or []
        if rows:
            return True
        stale_before = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        stale = (_service_client().table("cadivor_one_time_bom_orders")
                 .select("id").eq("user_id", _identity(user_id))
                 .eq("status", "reserved").lt("reserved_at", stale_before)
                 .limit(1).execute()).data or []
        return bool(stale)
    except Exception:
        # Fail closed: a database outage cannot authorize supplier lookups.
        return False


def reserved_credit(user_id: str, order_id: str) -> bool:
    if not _orders_available() or not order_id:
        return False
    try:
        rows = (_service_client().table("cadivor_one_time_bom_orders")
                .select("id").eq("id", str(UUID(order_id)))
                .eq("user_id", _identity(user_id)).eq("status", "reserved")
                .limit(1).execute()).data or []
        return bool(rows)
    except Exception:
        return False


def in_progress_credit(user_id: str) -> bool:
    if not _orders_available():
        return False
    try:
        rows = (_service_client().table("cadivor_one_time_bom_orders")
                .select("id").eq("user_id", _identity(user_id))
                .eq("status", "reserved").limit(1).execute()).data or []
        return bool(rows)
    except Exception:
        return False  # pending_checkout fails closed before any new purchase.


def pending_checkout(user_id: str) -> tuple[str, str] | None:
    """Return the existing Checkout URL, or a processing state, for this buyer."""
    if not enabled():
        return None
    try:
        rows = (_service_client().table("cadivor_one_time_bom_orders")
                .select("stripe_session_id").eq("user_id", _identity(user_id))
                .eq("status", "pending")
                .order("created_at", desc=True).limit(10).execute()).data or []
        session_id = next((row.get("stripe_session_id") for row in rows
                           if row.get("stripe_session_id")), None)
        if not session_id:
            return None
        import stripe
        from src.stripe_helper import _ensure_stripe_api_key
        _ensure_stripe_api_key()
        session = stripe.checkout.Session.retrieve(session_id)
        if session.status == "open" and session.url:
            return "open", str(session.url)
        return "processing", ""
    except Exception:
        return "processing", ""


def begin_checkout(user_id: str, verified_email: str, success_url: str, cancel_url: str) -> str:
    """Create a private pending order before issuing its one-time Stripe session."""
    if not enabled():
        raise OneTimeBOMError("One-time reports are temporarily unavailable.")
    uid = _identity(user_id)
    if pending_checkout(uid) is not None:
        raise OneTimeBOMError("A one-time checkout is already open or processing for this account.")
    from src.stripe_helper import create_one_time_bom_checkout
    email = str(verified_email or "").strip()
    if not email or "@" not in email:
        raise OneTimeBOMError("Verify your email before purchasing a report.")
    price_id = str(get_secret("STRIPE_ONE_TIME_BOM_REPORT_PRICE_ID", required=True))
    price_label(price_id)
    try:
        created = (_service_client().table("cadivor_one_time_bom_orders")
                   .insert({"user_id": uid, "price_id": price_id})
                   .execute()).data
        order_id = str(created[0]["id"])
        session = create_one_time_bom_checkout(
            price_id=price_id, user_email=email, user_id=uid,
            order_id=order_id, success_url=success_url, cancel_url=cancel_url,
        )
        session_id, url = str(session.id), str(session.url)
        saved = (_service_client().table("cadivor_one_time_bom_orders")
                 .update({"stripe_session_id": session_id})
                 .eq("id", order_id).eq("user_id", uid).eq("status", "pending")
                 .select("id").execute()).data
        if not saved or not url:
            # An orphaned checkout must never be presented for payment.
            import stripe
            stripe.checkout.Session.expire(session_id)
            raise OneTimeBOMError("Could not prepare secure checkout. Please retry.")
        return url
    except OneTimeBOMError:
        raise
    except Exception:
        raise OneTimeBOMError("Could not prepare secure checkout. Please retry.") from None


def reserve_credit(user_id: str) -> str:
    if not _orders_available():
        raise OneTimeBOMError("One-time reports are temporarily unavailable.")
    try:
        order_id = _service_client().rpc(
            "cadivor_reserve_one_time_bom_order", {"p_user_id": _identity(user_id)}
        ).execute().data
        if order_id:
            return str(UUID(str(order_id).strip('"')))
    except OneTimeBOMError:
        raise
    except Exception:
        raise OneTimeBOMError("Could not reserve your paid report. Please retry.") from None
    raise OneTimeBOMError("The payment has not been confirmed yet. Refresh in a moment.")


def attach_analysis(user_id: str, order_id: str, analysis_id: str) -> None:
    """Bind the reservation before the full BOM is saved."""
    try:
        attached = _service_client().rpc("cadivor_attach_one_time_bom_analysis", {
            "p_user_id": _identity(user_id), "p_order_id": str(UUID(order_id)),
            "p_analysis_id": str(UUID(analysis_id)),
        }).execute().data
        if attached is True:
            return
    except Exception:
        pass
    raise OneTimeBOMError("Could not prepare the saved report. Your purchase is still available.")


def release_credit(user_id: str, order_id: str) -> bool:
    if not order_id:
        return False
    try:
        released = _service_client().rpc("cadivor_release_one_time_bom_order", {
            "p_user_id": _identity(user_id), "p_order_id": str(UUID(order_id)),
        }).execute().data
        return released is True
    except Exception:
        # A reserved order remains auditable for support to release after a crash.
        return False


def consume_credit(user_id: str, order_id: str, analysis_id: str) -> None:
    try:
        result = _service_client().rpc("cadivor_consume_one_time_bom_order", {
            "p_user_id": _identity(user_id), "p_order_id": str(UUID(order_id)),
            "p_analysis_id": str(UUID(analysis_id)),
        }).execute().data
    except Exception:
        raise OneTimeBOMError("The analysis saved, but payment reconciliation needs attention. Contact support.") from None
    if result is not True:
        raise OneTimeBOMError("The analysis saved, but payment reconciliation needs attention. Contact support.")
