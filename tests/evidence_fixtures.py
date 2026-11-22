"""Small exact-source records for evidence-contract tests."""
from __future__ import annotations

from datetime import datetime, timezone


def retrieved_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def supplier_url(source: str, mpn: str) -> str:
    domains = {
        "DigiKey": "https://www.digikey.com/product/",
        "Mouser": "https://www.mouser.com/product/",
        "Newark": "https://www.newark.com/product/",
        "Nexar Supply": "https://nexar.com/product/",
    }
    return domains[source] + mpn


def live_supplier_part(
    mpn: str,
    *,
    lifecycle: str = "Active",
    stock: int = 1000,
    quantity: int = 10,
    unit_price: float | None = None,
    sources: tuple[str, ...] = ("DigiKey", "Mouser"),
    retrieved_at: str | None = None,
) -> dict:
    """Build an exact, fresh fixture without treating it as checkout evidence."""
    retrieved = retrieved_at or retrieved_now()
    source_rows = []
    # Distribute inventory across sources while keeping an exactly reconciled total.
    per_source = [stock // len(sources) for _ in sources]
    if per_source:
        per_source[0] += stock - sum(per_source)
    for source, source_stock in zip(sources, per_source):
        url = supplier_url(source, mpn)
        source_rows.append({
            "source": source,
            "mpn": mpn,
            "product_url": url,
            "retrieved_at": retrieved,
            "stock": source_stock,
        })

    row = {
        "MPN": mpn,
        "manufacturer_part_number": mpn,
        "Manufacturer": "Acme",
        "source": sources[0] if sources else "",
        "Best Source": sources[0] if sources else "",
        "product_url": supplier_url(sources[0], mpn) if sources else "",
        "retrieved_at": retrieved,
        "supplier_data_verified": bool(sources),
        "provider_status": "AVAILABLE" if sources else "NOT_CONFIGURED",
        "identity_source": "live-authorized-supplier" if sources else "",
        "evidence_source": "live-authorized-supplier" if sources else "",
        "Lifecycle": lifecycle,
        "lifecycle_evidence": [
            {
                "source": source,
                "mpn": mpn,
                "product_url": supplier_url(source, mpn),
                "status": lifecycle,
                "normalized_status": lifecycle.casefold(),
                "retrieved_at": retrieved,
            }
            for source in sources
        ],
        "Stock": stock,
        "stock_data_complete": True,
        "stock_data_sources": list(sources),
        "stock_evidence": source_rows,
        "Quantity": quantity,
        "Supplier Count": len(sources),
        "supplier_count": len(sources),
        "provider_health": {
            "configured_count": len(sources),
            "responded_count": len(sources),
            "failed_count": 0,
        },
        "Supplier Coverage Complete": len(sources) >= 2,
        "supplier_coverage_complete": len(sources) >= 2,
    }
    if unit_price is not None and sources:
        row["Unit Price"] = unit_price
        row["unit_price"] = unit_price
        row["unit_price_currency"] = "USD"
        row["price_source"] = sources[0]
        row["supplier_offers"] = [
            {
                "mpn": mpn,
                "distributor": source,
                "unit_price": unit_price if index == 0 else round(unit_price * 1.05, 4),
                "currency": "USD",
                "price_break_quantity": 1,
                "product_url": supplier_url(source, mpn),
                "retrieved_at": retrieved,
            }
            for index, source in enumerate(sources)
        ]
    return row
