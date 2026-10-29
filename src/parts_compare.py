"""Neutral engineering comparison of any two manufacturer part numbers.

This is not Alternative Finder. It reuses family profiles, parametric compare,
and supplier aggregation without recommending substitutes or exposing provider
diagnostics to customers.
"""
from __future__ import annotations

import time
from typing import Any, Mapping, MutableMapping

from src.component_family_profiles import get_family_profile, infer_family_id
from src.datasheet_comparison import (
    build_datasheet_comparison,
    build_engineering_evidence_assessment,
    diagnostic_comparison_rows,
    family_for_datasheet_review,
    merge_verified_datasheet_rows,
    user_facing_comparison_rows,
    user_may_view_comparison_diagnostics,
    verify_datasheet_identity,
)
from src.parametric_compare import engineering_confidence_from_rows
from src.part_images import normalize_supplier_image_url


FINDING_COMPATIBLE = "Compatible on available evidence"
FINDING_MATERIAL = "Material difference"
FINDING_NEEDS_DATA = "Needs data / engineering validation"

COMPARE_PARTS_PART_A_WIDGET_KEY = "compare_parts_part_a"
COMPARE_PARTS_PART_B_WIDGET_KEY = "compare_parts_part_b"
COMPARE_PARTS_RESULT_KEY = "compare_parts_result"
COMPARE_PARTS_LAST_SUBMIT_KEY = "compare_parts_last_submit"
COMPARE_PARTS_LAST_SUBMIT_AT_KEY = "compare_parts_last_submit_at"
COMPARE_PARTS_SUBMIT_DEBOUNCE_SECONDS = 2.0

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

USER_FACING_COMPARE_COLUMNS = (
    "Attribute",
    "Part A",
    "Part B",
    "Assessment",
    "Evidence",
)


def _normalize_mpn(value: Any) -> str:
    return str(value or "").strip().upper()


def resolve_compare_parts_submitted_mpn(*values: Any) -> str:
    """Return the first non-empty MPN from form/widget/session candidates.

    Streamlit can report an empty form return on the first Enter/click while the
    keyed widget session value already holds the typed MPN.
    """
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def claim_compare_parts_submit(
    session_state: MutableMapping[str, Any],
    part_a: str,
    part_b: str,
    *,
    debounce_seconds: float = COMPARE_PARTS_SUBMIT_DEBOUNCE_SECONDS,
    now: float | None = None,
) -> bool:
    """Claim one Compare Parts submit; reject empty, in-flight, or duplicate bursts."""
    a = _normalize_mpn(part_a)
    b = _normalize_mpn(part_b)
    if not a or not b:
        return False
    token = f"{a}|{b}"
    result = session_state.get(COMPARE_PARTS_RESULT_KEY)
    if isinstance(result, dict) and str(result.get("status") or "") == STATUS_RUNNING:
        prior = f"{_normalize_mpn(result.get('part_a'))}|{_normalize_mpn(result.get('part_b'))}"
        if prior == token:
            return False
    current = float(time.time() if now is None else now)
    last_token = str(session_state.get(COMPARE_PARTS_LAST_SUBMIT_KEY) or "")
    try:
        last_at = float(session_state.get(COMPARE_PARTS_LAST_SUBMIT_AT_KEY) or 0.0)
    except (TypeError, ValueError):
        last_at = 0.0
    if last_token == token and last_at > 0.0 and (current - last_at) < float(debounce_seconds):
        return False
    session_state[COMPARE_PARTS_LAST_SUBMIT_KEY] = token
    session_state[COMPARE_PARTS_LAST_SUBMIT_AT_KEY] = current
    return True


def map_status_to_assessment(status: str) -> str:
    normalized = str(status or "").strip()
    if normalized == "Match":
        return FINDING_COMPATIBLE
    if normalized == "Different":
        return FINDING_MATERIAL
    return FINDING_NEEDS_DATA


def user_facing_compare_rows(rows: list | None) -> list[dict]:
    """Project comparison rows to Part A / Part B columns without internal metadata."""
    projected: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        status = str(row.get("Status") or row.get("Result") or "")
        item = {
            "Attribute": row.get("Attribute", ""),
            "Part A": row.get("Original", row.get("Part A", "")),
            "Part B": row.get(
                "Candidate",
                row.get("Part B", row.get("Selected Alternative", "")),
            ),
            "Assessment": map_status_to_assessment(status),
            "Evidence": row.get("Evidence", ""),
        }
        if row.get("FixtureRow"):
            item["FixtureRow"] = True
        projected.append(item)
    return projected


def public_part_card(part: Mapping[str, Any] | None, *, family: str = "") -> dict[str, Any]:
    """Customer-safe identity fields only (no provider diagnostics)."""
    data = dict(part or {})
    profile = get_family_profile(family or infer_family_id(data))
    mpn = str(
        data.get("manufacturer_part_number")
        or data.get("Manufacturer Part Number")
        or ""
    ).strip()
    datasheet = str(data.get("datasheet_url") or "").strip()
    detail = str(data.get("product_detail_url") or "").strip()
    return {
        "mpn": mpn,
        "manufacturer": str(data.get("manufacturer") or "").strip(),
        "description": str(data.get("description") or "").strip(),
        "family": profile.id,
        "family_display_name": profile.display_name,
        "image_url": normalize_supplier_image_url(
            data.get("image_url") or data.get("photo_url") or data.get("PhotoUrl")
        ),
        "package": str(data.get("package") or "").strip(),
        "lifecycle_status": str(data.get("lifecycle_status") or "Unknown").strip() or "Unknown",
        "datasheet_url": datasheet if datasheet.startswith(("http://", "https://")) else "",
        "supplier_url": detail if detail.startswith(("http://", "https://")) else "",
        "found": bool(mpn),
    }


def resolve_comparison_family(part_a: Mapping[str, Any], part_b: Mapping[str, Any]) -> dict[str, Any]:
    """Choose the shared family profile used for attribute comparison."""
    family_a = infer_family_id(part_a)
    family_b = infer_family_id(part_b)
    if family_a == family_b:
        return {
            "family": family_a,
            "family_mismatch": False,
            "family_a": family_a,
            "family_b": family_b,
        }
    if family_a == "General" and family_b != "General":
        return {
            "family": family_b,
            "family_mismatch": False,
            "family_a": family_a,
            "family_b": family_b,
        }
    if family_b == "General" and family_a != "General":
        return {
            "family": family_a,
            "family_mismatch": False,
            "family_a": family_a,
            "family_b": family_b,
        }
    return {
        "family": "General",
        "family_mismatch": True,
        "family_a": family_a,
        "family_b": family_b,
    }


def derive_overall_finding(
    *,
    matches: int,
    differences: int,
    needs_data: int,
    evidence_status: str,
    family_mismatch: bool,
    requires_pinout_for_dropin: bool,
    pinout_matched: bool,
    required_missing: int = 0,
    required_differences: int = 0,
) -> str:
    """Map engineering coverage to a clear customer finding. Never invent a match."""
    if family_mismatch:
        return FINDING_MATERIAL
    if differences > 0 or required_differences > 0:
        return FINDING_MATERIAL
    if requires_pinout_for_dropin and not pinout_matched:
        return FINDING_NEEDS_DATA
    if matches <= 0 or required_missing > 0:
        return FINDING_NEEDS_DATA
    # Required attributes matched and no material differences: compatible on what
    # is available. Optional gaps remain visible as Needs data in the matrix.
    if differences == 0 and matches > 0:
        return FINDING_COMPATIBLE
    status = str(evidence_status or "").strip().casefold()
    if status in {"incomplete"} or (matches <= 1 and needs_data >= 5):
        return FINDING_NEEDS_DATA
    return FINDING_NEEDS_DATA


def _pinout_matched(rows: list[dict]) -> bool:
    for row in rows or []:
        key = str(row.get("Key") or "")
        label = str(row.get("Attribute") or "").casefold()
        if key == "pinout" or "pinout" in label:
            return str(row.get("Status") or "") == "Match"
    return False


def _part_is_catalog_fixture(part: Mapping[str, Any] | None) -> bool:
    data = dict(part or {})
    for key in ("catalog_fixture", "evidence_fixture", "test_fixture"):
        if bool(data.get(key)):
            return True
    return False


def _fixture_label(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    if text.casefold().startswith("[test fixture]"):
        return text
    if text.casefold() in {
        "not stated in retrieved evidence",
        "not available",
        "not found",
        "—",
        "-",
    }:
        return text
    if text.casefold().startswith("not stated in this "):
        return text
    return f"[Test fixture] {text}"


def _apply_fixture_labels(
    rows: list[dict],
    *,
    part_a: Mapping[str, Any],
    part_b: Mapping[str, Any],
    verified_a: bool = False,
    verified_b: bool = False,
) -> list[dict]:
    """Visibly mark catalog stub / synthetic supplier values used in tests."""
    del verified_a, verified_b  # kept for call-site compatibility
    label_a = _part_is_catalog_fixture(part_a)
    label_b = _part_is_catalog_fixture(part_b)
    if not label_a and not label_b:
        return list(rows or [])
    updated: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        current = dict(row)
        evidence_notes: list[str] = []
        fixture_used = False

        def _is_catalog_sourced(source_key: str, value: str) -> bool:
            source = str(current.get(source_key) or "").strip().casefold()
            if source == "evidence":
                return False
            if source == "catalog":
                return True
            # When no datasheet merge ran, catalog stubs have no OriginalSource tag.
            return bool(value) and not value.casefold().startswith("not stated")

        original = str(current.get("Original") or "").strip()
        if label_a and _is_catalog_sourced("OriginalSource", original):
            current["Original"] = _fixture_label(original)
            fixture_used = True
            evidence_notes.append(
                "Part A value is a [Test fixture] catalog/lifecycle stub, not live manufacturer evidence."
            )
        candidate = str(current.get("Candidate") or "").strip()
        if label_b and _is_catalog_sourced("CandidateSource", candidate):
            current["Candidate"] = _fixture_label(candidate)
            fixture_used = True
            evidence_notes.append(
                "Part B value is a [Test fixture] catalog/lifecycle stub, not live manufacturer evidence."
            )
        if fixture_used:
            current["FixtureRow"] = True
        if evidence_notes:
            existing = str(current.get("Evidence") or "").strip()
            current["Evidence"] = " ".join(
                part for part in (existing, *evidence_notes) if part
            ).strip()
        updated.append(current)
    return updated


def _fixture_kpi_summary(rows: list[dict]) -> dict[str, Any]:
    """Describe how [Test fixture] rows participate in visible KPI totals."""
    fixture_rows = [
        row for row in rows or []
        if isinstance(row, dict) and (
            bool(row.get("FixtureRow"))
            or "[test fixture]" in str(row.get("Original") or "").casefold()
            or "[test fixture]" in str(row.get("Candidate") or "").casefold()
            or "[test fixture]" in str(row.get("Part A") or "").casefold()
            or "[test fixture]" in str(row.get("Part B") or "").casefold()
        )
    ]
    by_status = {"Match": 0, "Different": 0, "Needs data": 0}
    labels: list[str] = []
    for row in fixture_rows:
        status = str(row.get("Status") or "Needs data")
        if status not in by_status:
            status = "Needs data"
        by_status[status] += 1
        label = str(row.get("Attribute") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return {
        "fixture_row_count": len(fixture_rows),
        "fixture_attributes": labels,
        "contributes_to_kpi_totals": True,
        "compatible_from_fixtures": by_status["Match"],
        "material_difference_from_fixtures": by_status["Different"],
        "needs_data_from_fixtures": by_status["Needs data"],
        "note": (
            f"{len(fixture_rows)} matrix row(s) use [Test fixture] stubs "
            f"({', '.join(labels) or 'none'}). Those rows are included in the "
            "Compatible / Material difference / Needs validation KPI totals and "
            "are not live manufacturer evidence."
            if fixture_rows
            else "No [Test fixture] rows are present in this comparison."
        ),
    }


def document_from_uploaded_datasheet(
    file_bytes: bytes,
    *,
    filename: str = "",
    manufacturer: str = "",
    mpn: str = "",
) -> dict[str, Any]:
    """Build a Compare Parts evidence document from a normal PDF upload.

    Values are cited only after verify_datasheet_identity confirms the entered
    manufacturer and exact MPN appear in the extractable text.
    """
    from src.datasheet_qa import extract_uploaded_datasheet

    name = str(filename or "datasheet.pdf").strip() or "datasheet.pdf"
    extracted = extract_uploaded_datasheet(bytes(file_bytes or b""), filename=name)
    pages: list[dict[str, Any]] = []
    for page in extracted.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        entry = dict(page)
        entry.setdefault("document", name)
        pages.append(entry)
    available = bool(extracted.get("available")) and bool(pages)
    doc: dict[str, Any] = {
        "available": available,
        "pages": pages,
        "reason": str(extracted.get("reason") or ""),
        "source_name": f"Uploaded datasheet ({name})",
        "source_type": "uploaded_datasheet",
        "extraction_method": "uploaded_pdf_native_text",
        "source_url": f"upload://{name}",
        "final_url": f"upload://{name}",
        "filename": name,
        "state": "extracted" if available else "unavailable",
        "content_fingerprint": extracted.get("content_fingerprint") or "",
        "page_count": int(extracted.get("page_count") or 0),
        "byte_count": int(extracted.get("byte_count") or 0),
    }
    identity = verify_datasheet_identity(
        doc, manufacturer=str(manufacturer or "").strip(), mpn=str(mpn or "").strip()
    )
    if not available:
        status = "error"
        detail = str(extracted.get("reason") or "Upload could not be read.")
    elif identity.get("verified"):
        status = "available"
        named = f"{str(manufacturer or '').strip()} {str(mpn or '').strip()}".strip()
        detail = (
            f"Uploaded datasheet named {named}. Values may be cited from this document."
        )
    else:
        status = "not_found"
        detail = str(
            identity.get("reason")
            or "Uploaded datasheet did not verify the entered manufacturer and exact MPN."
        )
        detail = f"{detail} No values were taken from the upload."
    doc["upload_identity"] = identity
    doc["evidence_sources"] = [
        {
            "source": "upload",
            "source_type": "uploaded_datasheet",
            "url": f"upload://{name}",
            "status": status,
            "detail": detail,
            "identity_verified": bool(identity.get("verified")),
        }
    ]
    return doc


def summarize_exact_mpn_access_blockers(
    *,
    evidence_sources: Mapping[str, Any] | None,
    datasheet_identity: Mapping[str, Any] | None,
    mpn_a: str = "",
    mpn_b: str = "",
    manufacturer_a: str = "",
    manufacturer_b: str = "",
) -> dict[str, Any]:
    """Report remaining permitted-source blockers when exact-MPN evidence is missing."""
    sources_map = evidence_sources if isinstance(evidence_sources, Mapping) else {}
    identity_map = datasheet_identity if isinstance(datasheet_identity, Mapping) else {}
    digikey_lead = "https://www.digikey.com/en/products/detail/ohmite/RES10K/258353"
    permitted_paths = [
        {
            "provider": "DigiKey API",
            "integration": "integrations/digikey_client.py",
            "required_configuration": ["DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET"],
            "discovery_lead": digikey_lead,
            "note": (
                "Configure DigiKey OAuth client credentials in the product secrets "
                "store or environment. Public DigiKey HTML is HTTP 403-blocked and "
                "is never used. Do not paste secrets into chat."
            ),
        },
        {
            "provider": "Mouser API",
            "integration": "integrations/mouser_client.py",
            "required_configuration": ["MOUSER_API_KEY"],
            "note": (
                "Configure the Mouser API key in the product secrets store or "
                "environment when DigiKey is unavailable."
            ),
        },
        {
            "provider": "Newark / element14 API",
            "integration": "integrations/newark_client.py",
            "required_configuration": ["NEWARK_API_KEY"],
            "note": (
                "Configure the Newark/element14 API key in the product secrets store "
                "or environment when DigiKey is unavailable."
            ),
        },
        {
            "provider": "Exact-MPN datasheet upload",
            "path": "Compare Parts → Optional: upload exact-MPN datasheet",
            "required_configuration": [],
            "note": (
                "Upload a text-based PDF through the Compare Parts upload control. "
                "Values are shown only after the file names the entered manufacturer "
                "and exact MPN."
            ),
        },
    ]
    blockers: list[dict[str, Any]] = []
    unverified: list[str] = []
    for side, mpn, manufacturer in (
        ("part_a", mpn_a, manufacturer_a),
        ("part_b", mpn_b, manufacturer_b),
    ):
        identity = identity_map.get(side) if isinstance(identity_map.get(side), Mapping) else {}
        if identity.get("verified"):
            continue
        token = str(mpn or "").strip()
        if token:
            unverified.append(token)
        side_sources = list(sources_map.get(side) or [])
        digikey_api = next(
            (
                row
                for row in side_sources
                if isinstance(row, Mapping)
                and row.get("source_type") == "authorized_distributor_api_lookup"
                and str(row.get("source") or "") == "DigiKey"
            ),
            None,
        )
        if isinstance(digikey_api, Mapping) and digikey_api.get("status") == "not_configured":
            blockers.append(
                {
                    "mpn": token,
                    "side": side,
                    "provider": "DigiKey API",
                    "status": "not_configured",
                    "required_configuration": [
                        "DIGIKEY_CLIENT_ID",
                        "DIGIKEY_CLIENT_SECRET",
                    ],
                    "detail": str(digikey_api.get("detail") or ""),
                    "discovery_lead": digikey_lead if token.upper() == "RES10K" else "",
                }
            )
        upload_row = next(
            (
                row
                for row in side_sources
                if isinstance(row, Mapping)
                and row.get("source_type") == "uploaded_datasheet"
            ),
            None,
        )
        if upload_row is None:
            blockers.append(
                {
                    "mpn": token,
                    "side": side,
                    "provider": "Exact-MPN datasheet upload",
                    "status": "not_provided",
                    "required_configuration": [],
                    "detail": (
                        "No exact-MPN datasheet was uploaded for this part. Use "
                        "Compare Parts → Optional: upload exact-MPN datasheet when "
                        "authorized APIs are unavailable."
                    ),
                }
            )
        elif not upload_row.get("identity_verified"):
            blockers.append(
                {
                    "mpn": token,
                    "side": side,
                    "provider": "Exact-MPN datasheet upload",
                    "status": str(upload_row.get("status") or "not_found"),
                    "required_configuration": [],
                    "detail": str(upload_row.get("detail") or ""),
                }
            )
        arrow_rows = [
            row
            for row in side_sources
            if isinstance(row, Mapping)
            and str(row.get("source_type") or "") == "arrow_authorized_product_page"
        ]
        galco_rows = [
            row
            for row in side_sources
            if isinstance(row, Mapping)
            and str(row.get("source_type") or "") == "galco_authorized_product_page"
        ]
        rs_rows = [
            row
            for row in side_sources
            if isinstance(row, Mapping)
            and str(row.get("source_type") or "") == "rs_group_authorized_product_page"
        ]
        for row in rs_rows:
            blockers.append(
                {
                    "mpn": token,
                    "side": side,
                    "provider": "RS Group authorized product page",
                    "status": str(row.get("status") or ""),
                    "required_configuration": [],
                    "detail": str(row.get("detail") or ""),
                    "url": str(row.get("url") or ""),
                    "retrieved_at": str(row.get("retrieved_at") or ""),
                }
            )
        for row in arrow_rows:
            blockers.append(
                {
                    "mpn": token,
                    "side": side,
                    "provider": "Arrow authorized product page",
                    "status": str(row.get("status") or ""),
                    "required_configuration": [],
                    "detail": str(row.get("detail") or ""),
                    "url": str(row.get("url") or ""),
                    "retrieved_at": str(row.get("retrieved_at") or ""),
                }
            )
        for row in galco_rows:
            blockers.append(
                {
                    "mpn": token,
                    "side": side,
                    "provider": "Galco authorized product page",
                    "status": str(row.get("status") or ""),
                    "required_configuration": [],
                    "detail": str(row.get("detail") or ""),
                    "url": str(row.get("url") or ""),
                    "retrieved_at": str(row.get("retrieved_at") or ""),
                }
            )
        if token.upper() == "RES10K" and not identity.get("verified"):
            maker = str(manufacturer or "Ohmite").strip() or "Ohmite"
            arrow_status = next((str(row.get("status") or "") for row in arrow_rows), "")
            galco_status = next((str(row.get("status") or "") for row in galco_rows), "")
            rs_status = next((str(row.get("status") or "") for row in rs_rows), "")
            blockers.append(
                {
                    "mpn": token,
                    "side": side,
                    "provider": "manufacturer_or_authorized_distributor",
                    "status": "unverified",
                    "required_configuration": [
                        "DIGIKEY_CLIENT_ID",
                        "DIGIKEY_CLIENT_SECRET",
                    ],
                    "detail": (
                        "RES10K remains unverified after authorized-distributor page "
                        f"probes (RS Group status={rs_status or 'not_probed'}; "
                        f"Arrow status={arrow_status or 'not_probed'}; "
                        f"Galco status={galco_status or 'not_probed'}). DigiKey public "
                        "HTML is HTTP 403-blocked (not used). Configure "
                        "DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET in the product "
                        "secrets store, or upload an exact-MPN datasheet that names "
                        f"{maker} and RES10K — only after these page-access blockers."
                    ),
                    "discovery_lead": digikey_lead,
                }
            )
    # Prefer authorized distributor product pages ahead of API/upload fallbacks.
    permitted_paths = [
        {
            "provider": "RS Group authorized product page",
            "url": "https://uk.rs-online.com/web/p/potentiometers/70585847",
            "stock_number": "70585847",
            "required_configuration": [],
            "note": (
                "Ohmite-authorized RS Group exact-MPN product detail. Search/stock "
                "listings are discovery leads only. Values require retrieved detail "
                "HTML naming Ohmite and RES10K. HTTP 403 bodies are never used."
            ),
        },
        {
            "provider": "Arrow authorized product page",
            "url": "https://www.arrow.com/en/products/res10k/ohmite",
            "required_configuration": [],
            "note": (
                "Ohmite-authorized Arrow exact-MPN page. Values are cited only when "
                "the retrieved HTML names Ohmite and RES10K. Timeouts fail closed."
            ),
        },
        {
            "provider": "Galco authorized product page",
            "url": "https://www.galco.com/buy/Ohmite/RES10K",
            "required_configuration": [],
            "note": (
                "Ohmite-authorized Galco product probe. Cloudflare / HTTP 403 bodies "
                "are never used as evidence."
            ),
        },
        *permitted_paths,
    ]
    return {
        "unverified_mpns": unverified,
        "blockers": blockers,
        "permitted_paths": permitted_paths,
    }


def _comparison_document(
    part: Mapping[str, Any],
    explicit: Mapping[str, Any] | None,
    *,
    extract_linked: bool,
    mpn: str = "",
) -> dict[str, Any] | None:
    """Use attached evidence, or search manufacturer/distributor sources when asked."""
    requested_mpn = str(
        mpn
        or part.get("manufacturer_part_number")
        or part.get("Manufacturer Part Number")
        or ""
    ).strip()
    manufacturer = str(part.get("manufacturer") or "").strip()

    explicit_doc: dict[str, Any] | None = None
    if isinstance(explicit, Mapping):
        explicit_doc = dict(explicit)
        identity = verify_datasheet_identity(
            explicit_doc, manufacturer=manufacturer, mpn=requested_mpn
        )
        if identity.get("verified") or not extract_linked:
            explicit_doc.setdefault("evidence_sources", [])
            return explicit_doc

    embedded = part.get("datasheet_document")
    if isinstance(embedded, Mapping) and explicit_doc is None:
        return dict(embedded)
    if not extract_linked:
        return explicit_doc

    from src.compare_evidence_search import gather_part_evidence

    evidence = gather_part_evidence(
        mpn=requested_mpn,
        manufacturer=manufacturer,
        datasheet_url=str(part.get("datasheet_url") or "").strip(),
        product_detail_url=str(
            part.get("product_detail_url")
            or part.get("supplier_url")
            or part.get("Product URL")
            or ""
        ).strip(),
        probe_distributor_pages=True,
    )
    sources = list(evidence.get("sources") or [])
    if explicit_doc is not None:
        sources = list(explicit_doc.get("evidence_sources") or []) + sources
    verified = list(evidence.get("verified_documents") or [])
    if verified:
        chosen = dict(verified[0])
        chosen["evidence_sources"] = sources
        chosen["evidence_search"] = {
            "verified_document_count": len(verified),
            "document_count": len(evidence.get("documents") or []),
        }
        chosen.setdefault("state", "extracted")
        return chosen

    if explicit_doc is not None:
        # Keep the upload attached for diagnostics, but do not treat it as verified.
        explicit_doc["evidence_sources"] = sources
        explicit_doc["evidence_search"] = {
            "verified_document_count": 0,
            "document_count": len(evidence.get("documents") or []),
        }
        return explicit_doc

    primary = evidence.get("primary_document")
    if isinstance(primary, Mapping):
        chosen = dict(primary)
        chosen["evidence_sources"] = sources
        chosen["evidence_search"] = {
            "verified_document_count": 0,
            "document_count": len(evidence.get("documents") or []),
        }
        chosen.setdefault(
            "state",
            "extracted" if chosen.get("pages") else "unavailable",
        )
        return chosen

    url = str(part.get("datasheet_url") or "").strip()
    return {
        "available": False,
        "pages": [],
        "reason": "No manufacturer or authorized distributor source verified this exact MPN.",
        "state": "unavailable",
        "final_url": url,
        "evidence_sources": sources,
        "evidence_search": {"verified_document_count": 0, "document_count": 0},
    }


def _part_for_verified_datasheet(
    part: Mapping[str, Any],
    document: Mapping[str, Any] | None,
    *,
    mpn: str,
) -> dict[str, Any]:
    """Let a verified datasheet identify the family when the catalog description does not."""
    updated = dict(part)
    if not isinstance(document, Mapping):
        return updated
    identity = verify_datasheet_identity(
        document,
        manufacturer=str(updated.get("manufacturer") or ""),
        mpn=mpn or str(updated.get("manufacturer_part_number") or ""),
    )
    if not identity["verified"]:
        return updated
    identified = family_for_datasheet_review(updated, document)
    if identified == "General electronic component":
        return updated
    if infer_family_id(updated) == "General electronic component":
        updated["description"] = (
            f"{updated.get('description') or ''} {get_family_profile(identified).display_name}"
        ).strip()
    return updated


def build_parts_comparison(
    part_a: Mapping[str, Any],
    part_b: Mapping[str, Any],
    *,
    part_a_mpn: str = "",
    part_b_mpn: str = "",
    datasheet_a: Mapping[str, Any] | None = None,
    datasheet_b: Mapping[str, Any] | None = None,
    extract_linked_datasheets: bool = False,
) -> dict[str, Any]:
    """Build a neutral family-aware comparison between two retrieved parts."""
    mpn_a = part_a_mpn or str(part_a.get("manufacturer_part_number") or "")
    mpn_b = part_b_mpn or str(part_b.get("manufacturer_part_number") or "")
    document_a = _comparison_document(
        part_a, datasheet_a, extract_linked=extract_linked_datasheets, mpn=mpn_a
    )
    document_b = _comparison_document(
        part_b, datasheet_b, extract_linked=extract_linked_datasheets, mpn=mpn_b
    )
    part_a = _part_for_verified_datasheet(part_a, document_a, mpn=mpn_a)
    part_b = _part_for_verified_datasheet(part_b, document_b, mpn=mpn_b)
    family_meta = resolve_comparison_family(part_a, part_b)
    family = str(family_meta["family"])
    profile = get_family_profile(family)

    # Force family used by datasheet comparison by tagging Part A when families align
    # through General fallback; build_datasheet_comparison infers from Part A.
    part_a_for_compare = dict(part_a)
    if not family_meta["family_mismatch"] and infer_family_id(part_a_for_compare) == "General":
        part_a_for_compare["description"] = (
            f"{part_a_for_compare.get('description') or ''} {profile.display_name}"
        ).strip()

    comparison = build_datasheet_comparison(dict(part_a_for_compare), dict(part_b))
    if family_meta["family_mismatch"]:
        # Re-run on General so only shared mechanical fields are compared.
        from src.component_family_profiles import comparison_fields
        from src.parametric_compare import compare_field_values

        fields = comparison_fields(get_family_profile("General"))
        rows: list[dict] = []
        counts = {"Match": 0, "Different": 0, "Needs data": 0}
        for spec in fields:
            a_val = str(part_a.get(spec.key) or "").strip()
            b_val = str(part_b.get(spec.key) or "").strip()
            if spec.key == "pin_count":
                from integrations.pin_count import effective_pin_count

                a_count = effective_pin_count(part_a)
                b_count = effective_pin_count(part_b)
                a_val = str(a_count) if a_count > 0 else ""
                b_val = str(b_count) if b_count > 0 else ""
            status, note = compare_field_values(a_val, b_val, spec)
            counts[status] += 1
            rows.append(
                {
                    "Attribute": spec.label,
                    "Key": spec.key,
                    "Required": bool(spec.required),
                    "CompareMode": spec.compare,
                    "ValueRole": spec.value_role,
                    "Original": a_val or "Not available",
                    "Candidate": b_val or "Not available",
                    "Status": status,
                    "Evidence": note,
                }
            )
        # Leading family-mismatch row is explicit and never inferred as a match.
        rows.insert(
            0,
            {
                "Attribute": "Component family",
                "Key": "family",
                "Required": True,
                "CompareMode": "exact",
                "ValueRole": "identity",
                "Original": get_family_profile(family_meta["family_a"]).display_name,
                "Candidate": get_family_profile(family_meta["family_b"]).display_name,
                "Status": "Different",
                "Evidence": (
                    "Part A and Part B resolve to different component families; "
                    "family-specific electrical attributes are not compared as equivalents."
                ),
            }
        )
        counts["Different"] += 1
        comparison = {
            "family": "General",
            "family_display_name": get_family_profile("General").display_name,
            "scoring_mode": get_family_profile("General").scoring_mode,
            "requires_pinout_for_dropin": False,
            "rows": rows,
            "counts": counts,
        }

    rows = list(comparison.get("rows") or [])
    rows, datasheet_identity, review_warnings = merge_verified_datasheet_rows(
        rows,
        family=str(comparison.get("family") or family),
        document_a=document_a,
        document_b=document_b,
        manufacturer_a=str(part_a.get("manufacturer") or ""),
        manufacturer_b=str(part_b.get("manufacturer") or ""),
        mpn_a=mpn_a,
        mpn_b=mpn_b,
    )
    rows = _apply_fixture_labels(
        rows,
        part_a=part_a,
        part_b=part_b,
        verified_a=bool((datasheet_identity.get("part_a") or {}).get("verified")),
        verified_b=bool((datasheet_identity.get("part_b") or {}).get("verified")),
    )
    counts = {"Match": 0, "Different": 0, "Needs data": 0}
    for row in rows:
        status = str(row.get("Status") or "Needs data")
        if status not in counts:
            status = "Needs data"
        counts[status] += 1
    confidence = engineering_confidence_from_rows(
        rows,
        requires_pinout_for_dropin=bool(comparison.get("requires_pinout_for_dropin")),
    )
    assessment = build_engineering_evidence_assessment(
        counts,
        comparison_rows=rows,
        family=str(comparison.get("family") or family),
    )
    finding = derive_overall_finding(
        matches=int(confidence.get("matches") or 0),
        differences=int(confidence.get("differences") or 0),
        needs_data=int(confidence.get("needs_data") or 0),
        evidence_status=str(confidence.get("engineering_evidence_status") or ""),
        family_mismatch=bool(family_meta["family_mismatch"]),
        requires_pinout_for_dropin=bool(comparison.get("requires_pinout_for_dropin")),
        pinout_matched=_pinout_matched(rows),
        required_missing=int(confidence.get("required_missing") or 0),
        required_differences=int(confidence.get("required_differences") or 0),
    )

    card_a = public_part_card(part_a, family=str(family_meta["family_a"]))
    card_b = public_part_card(part_b, family=str(family_meta["family_b"]))
    if part_a_mpn and not card_a["mpn"]:
        card_a["mpn"] = _normalize_mpn(part_a_mpn)
    if part_b_mpn and not card_b["mpn"]:
        card_b["mpn"] = _normalize_mpn(part_b_mpn)
    if _part_is_catalog_fixture(part_a):
        card_a["lifecycle_status"] = _fixture_label(card_a.get("lifecycle_status"))
        card_a["catalog_fixture"] = True
    if _part_is_catalog_fixture(part_b):
        card_b["lifecycle_status"] = _fixture_label(card_b.get("lifecycle_status"))
        card_b["catalog_fixture"] = True

    evidence_sources = {
        "part_a": list((document_a or {}).get("evidence_sources") or []),
        "part_b": list((document_b or {}).get("evidence_sources") or []),
    }
    fixture_kpi = _fixture_kpi_summary(rows)
    verified_a = bool((datasheet_identity.get("part_a") or {}).get("verified"))
    verified_b = bool((datasheet_identity.get("part_b") or {}).get("verified"))
    asymmetry_note = ""
    if verified_b and not verified_a:
        asymmetry_note = (
            "One-sided evidence: Part B has manufacturer-verified values; "
            "Part A does not. Rows with Part B values and empty Part A remain Needs validation."
        )
    elif verified_a and not verified_b:
        asymmetry_note = (
            "One-sided evidence: Part A has manufacturer-verified values; "
            "Part B does not. Rows with Part A values and empty Part B remain Needs validation."
        )

    user_rows = user_facing_compare_rows(rows)
    notes = [
        "Engineering compatibility is separate from any supplier substitute relationship.",
        "Missing attributes stay missing; Cadivor does not infer a match.",
        "Values are used only when a retrieved source names the entered manufacturer and exact MPN.",
        fixture_kpi["note"],
        (
            "Synthetic [Test fixture] markers are applied only when a part record "
            "explicitly sets catalog_fixture/evidence_fixture. The production "
            "lookup_part_for_compare path strips those flags and clears fixture "
            "Mounting/Lifecycle values, so stubs cannot enter the normal "
            "supplier-evidence path as live catalog data."
        ),
    ]
    if asymmetry_note:
        notes.append(asymmetry_note)
    access_blockers = summarize_exact_mpn_access_blockers(
        evidence_sources=evidence_sources,
        datasheet_identity=datasheet_identity,
        mpn_a=mpn_a,
        mpn_b=mpn_b,
        manufacturer_a=str(part_a.get("manufacturer") or ""),
        manufacturer_b=str(part_b.get("manufacturer") or ""),
    )
    if access_blockers.get("unverified_mpns"):
        notes.append(
            "Exact-MPN values stay unverified until a permitted manufacturer page, "
            "authorized-distributor API, or identity-verified upload cites them. "
            "See access_blockers for the remaining configuration path."
        )
    return {
        "part_a": card_a,
        "part_b": card_b,
        "family": str(comparison.get("family") or family),
        "family_display_name": str(
            comparison.get("family_display_name")
            or get_family_profile(family).display_name
        ),
        "family_mismatch": bool(family_meta["family_mismatch"]),
        "finding": finding,
        "engineering_evidence_summary": assessment.get("engineering_evidence_summary", ""),
        "engineering_evidence_status": assessment.get("engineering_evidence_status", ""),
        "counts": {
            "compatible": int(counts.get("Match") or 0),
            "material_difference": int(counts.get("Different") or 0),
            "needs_data": int(counts.get("Needs data") or 0),
        },
        "rows": user_rows,
        "diagnostic_rows": diagnostic_comparison_rows(rows),
        "datasheet_identity": datasheet_identity,
        "evidence_sources": evidence_sources,
        "access_blockers": access_blockers,
        "review_warnings": review_warnings,
        "fixture_kpi": fixture_kpi,
        "evidence_asymmetry_note": asymmetry_note,
        "fixture_production_isolation": {
            "production_lookup_strips_fixture_flags": True,
            "production_lookup_clears_fixture_mounting_lifecycle": True,
            "fixture_flags": list(_PRODUCTION_FIXTURE_KEYS),
            "fixture_value_fields": list(_PRODUCTION_FIXTURE_VALUE_FIELDS),
            "note": (
                "Mounting and Lifecycle [Test fixture] stubs contribute to visible "
                "KPI totals only when explicitly flagged on in-process test parts. "
                "lookup_part_for_compare strips fixture flags and clears fixture "
                "Mounting/Lifecycle values so synthetic stubs cannot enter the "
                "normal production evidence path as unlabeled catalog data."
            ),
        },
        "supplier_substitute_claim": False,
        "notes": notes,
    }


_PRODUCTION_FIXTURE_KEYS = (
    "catalog_fixture",
    "evidence_fixture",
    "test_fixture",
    "FixtureRow",
)

# Mounting / lifecycle stubs used by evidence scripts. If a production lookup
# payload arrives already marked as a test fixture, clear these fields entirely—
# stripping the marker keys alone would still let synthetic values look like
# live supplier catalog evidence.
_PRODUCTION_FIXTURE_VALUE_FIELDS = (
    "mounting_style",
    "Mounting Style",
    "Mounting",
    "mounting",
    "lifecycle_status",
    "Lifecycle",
    "lifecycle",
    "lifecycle_evidence",
    "lifecycle_conflict",
)


def _value_has_fixture_prefix(value: object) -> bool:
    return str(value or "").strip().casefold().startswith("[test fixture]")


def _part_arrived_as_test_fixture(part: Mapping[str, Any] | None) -> bool:
    data = dict(part or {})
    if any(bool(data.get(key)) for key in ("catalog_fixture", "evidence_fixture", "test_fixture")):
        return True
    for key in _PRODUCTION_FIXTURE_VALUE_FIELDS:
        if _value_has_fixture_prefix(data.get(key)):
            return True
    return False


def _sanitize_production_lookup_part(part: Mapping[str, Any] | None) -> dict[str, Any]:
    """Block synthetic fixture Mounting/Lifecycle values from production lookup.

    Evidence scripts may set catalog_fixture and [Test fixture] stubs. The normal
    Compare Parts lookup path must not keep those stubs as unlabeled catalog data.
    """
    data = dict(part or {})
    arrived_as_fixture = _part_arrived_as_test_fixture(data)
    for key in _PRODUCTION_FIXTURE_KEYS:
        data.pop(key, None)
    if arrived_as_fixture:
        for key in _PRODUCTION_FIXTURE_VALUE_FIELDS:
            data.pop(key, None)
    for key, value in list(data.items()):
        if _value_has_fixture_prefix(value):
            data.pop(key, None)
    return data


def _strip_test_fixture_flags(part: Mapping[str, Any] | None) -> dict[str, Any]:
    """Backward-compatible alias for production fixture sanitization."""
    return _sanitize_production_lookup_part(part)


def lookup_part_for_compare(part_number: str) -> dict[str, Any]:
    """Retrieve normalized supplier data without requiring Octopart."""
    from integrations.supplier_aggregator import get_best_part_data

    requested = str(part_number or "").strip()
    if not requested:
        return {}
    result = get_best_part_data(requested) or {}
    health = result.get("provider_health") if isinstance(result.get("provider_health"), dict) else {}
    # Strip diagnostics / raw provider payloads before they can reach the UI layer.
    sanitized = {
        key: value
        for key, value in result.items()
        if not str(key).startswith("diagnostic_")
        and key
        not in {
            "provider_health",
            "all_supplier_results",
            "octopart_sellers",
            "error",
            "failure_category",
            *_PRODUCTION_FIXTURE_KEYS,
        }
    }
    # Defense in depth: never promote synthetic fixture Mounting/Lifecycle stubs.
    sanitized = _sanitize_production_lookup_part(sanitized)
    if health:
        sanitized["catalog_search"] = {
            "configured_count": health.get("configured_count"),
            "successful_count": health.get("successful_count"),
            "failed_count": health.get("failed_count"),
            "part_not_found_count": health.get("part_not_found_count"),
            "failed_sources": list(health.get("failed_sources") or []),
            "available_sources": list(health.get("available_sources") or []),
            "not_configured_sources": list(health.get("not_configured_sources") or []),
            "summary_message": health.get("summary_message") or "",
        }
    return sanitized


def _datasheet_from_upload_payload(
    upload: Any,
    *,
    manufacturer: str,
    mpn: str,
) -> dict[str, Any] | None:
    """Normalize a Streamlit UploadedFile or {bytes, filename} into evidence."""
    if upload is None:
        return None
    if isinstance(upload, Mapping) and "pages" in upload:
        return dict(upload)
    payload = b""
    filename = ""
    if isinstance(upload, Mapping):
        raw = upload.get("bytes")
        if raw is None:
            raw = upload.get("file_bytes")
        payload = bytes(raw or b"")
        filename = str(upload.get("filename") or upload.get("name") or "").strip()
    else:
        getter = getattr(upload, "getvalue", None)
        if callable(getter):
            payload = bytes(getter() or b"")
        elif isinstance(upload, (bytes, bytearray)):
            payload = bytes(upload)
        else:
            return None
        filename = str(getattr(upload, "name", "") or "").strip()
    if not payload:
        return None
    return document_from_uploaded_datasheet(
        payload,
        filename=filename or "datasheet.pdf",
        manufacturer=manufacturer,
        mpn=mpn,
    )


def run_compare_parts(
    part_a_mpn: str,
    part_b_mpn: str,
    *,
    datasheets: Mapping[str, Any] | None = None,
    datasheet_uploads: Mapping[str, Any] | None = None,
    extract_linked_datasheets: bool = True,
) -> dict[str, Any]:
    """End-to-end Compare Parts run used by the authenticated page."""
    a = str(part_a_mpn or "").strip()
    b = str(part_b_mpn or "").strip()
    if not a or not b:
        return {
            "status": STATUS_FAILED,
            "error": "Enter both Part A and Part B manufacturer part numbers.",
            "part_a": a,
            "part_b": b,
        }
    if _normalize_mpn(a) == _normalize_mpn(b):
        return {
            "status": STATUS_FAILED,
            "error": "Part A and Part B must be different manufacturer part numbers.",
            "part_a": a,
            "part_b": b,
        }
    data_a = lookup_part_for_compare(a)
    data_b = lookup_part_for_compare(b)
    supplied: dict[str, Any] = {}
    if isinstance(datasheets, Mapping):
        if isinstance(datasheets.get("a"), Mapping):
            supplied["a"] = datasheets["a"]
        if isinstance(datasheets.get("b"), Mapping):
            supplied["b"] = datasheets["b"]
    uploads = datasheet_uploads if isinstance(datasheet_uploads, Mapping) else {}
    if "a" not in supplied and uploads.get("a") is not None:
        built = _datasheet_from_upload_payload(
            uploads.get("a"),
            manufacturer=str(data_a.get("manufacturer") or ""),
            mpn=a,
        )
        if built is not None:
            supplied["a"] = built
    if "b" not in supplied and uploads.get("b") is not None:
        built = _datasheet_from_upload_payload(
            uploads.get("b"),
            manufacturer=str(data_b.get("manufacturer") or ""),
            mpn=b,
        )
        if built is not None:
            supplied["b"] = built
    comparison = build_parts_comparison(
        data_a,
        data_b,
        part_a_mpn=a,
        part_b_mpn=b,
        datasheet_a=supplied.get("a") if isinstance(supplied.get("a"), Mapping) else None,
        datasheet_b=supplied.get("b") if isinstance(supplied.get("b"), Mapping) else None,
        extract_linked_datasheets=extract_linked_datasheets,
    )
    if not comparison["part_a"]["found"] and not comparison["part_b"]["found"]:
        return {
            "status": STATUS_FAILED,
            "error": "Cadivor could not retrieve supplier data for either part.",
            "part_a": a,
            "part_b": b,
            "comparison": comparison,
        }
    return {
        "status": STATUS_COMPLETED,
        "part_a": a,
        "part_b": b,
        "comparison": comparison,
        "error": "",
    }


def run_compare_parts_many(
    part_mpns: list[str] | tuple[str, ...],
    *,
    datasheets: list[Mapping[str, Any] | None] | None = None,
    extract_linked_datasheets: bool = True,
) -> dict[str, Any]:
    """Compare two or three parts side by side, using Part A as the baseline.

    Each entered MPN is retrieved once. Part B and optional Part C are compared
    independently with Part A, so the table never implies that one candidate was
    validated against another candidate.
    """
    parts = [str(value or "").strip() for value in part_mpns or ()]
    while parts and not parts[-1]:
        parts.pop()
    token = [_normalize_mpn(value) for value in parts]
    if len(parts) < 2:
        return {
            "status": STATUS_FAILED,
            "error": "Enter Part A and Part B. You can add a third part before comparing.",
            "part_numbers": parts,
        }
    if len(parts) > 3:
        return {
            "status": STATUS_FAILED,
            "error": "Compare up to three parts at a time.",
            "part_numbers": parts,
        }
    if any(not value for value in token):
        return {
            "status": STATUS_FAILED,
            "error": "Enter a manufacturer part number for each selected part.",
            "part_numbers": parts,
        }
    if len(set(token)) != len(token):
        return {
            "status": STATUS_FAILED,
            "error": "Each comparison slot must use a different manufacturer part number.",
            "part_numbers": parts,
        }

    retrieved = [lookup_part_for_compare(mpn) for mpn in parts]
    supplied_documents = list(datasheets or [])
    pair_comparisons = [
        build_parts_comparison(
            retrieved[0],
            retrieved[index],
            part_a_mpn=parts[0],
            part_b_mpn=parts[index],
            datasheet_a=supplied_documents[0] if supplied_documents and isinstance(supplied_documents[0], Mapping) else None,
            datasheet_b=(
                supplied_documents[index]
                if index < len(supplied_documents) and isinstance(supplied_documents[index], Mapping)
                else None
            ),
            extract_linked_datasheets=extract_linked_datasheets,
        )
        for index in range(1, len(parts))
    ]
    cards = [pair_comparisons[0]["part_a"]] + [
        comparison["part_b"] for comparison in pair_comparisons
    ]
    if not any(card.get("found") for card in cards):
        return {
            "status": STATUS_FAILED,
            "error": "Cadivor could not retrieve supplier data for these parts.",
            "part_numbers": parts,
        }

    by_pair: list[dict[str, dict[str, Any]]] = []
    attribute_order: list[str] = []
    for comparison in pair_comparisons:
        current: dict[str, dict[str, Any]] = {}
        for row in comparison.get("rows") or []:
            if not isinstance(row, dict):
                continue
            label = str(row.get("Attribute") or "").strip()
            if not label:
                continue
            key = label.casefold()
            current[key] = row
            if key not in attribute_order:
                attribute_order.append(key)
        by_pair.append(current)

    rows: list[dict[str, Any]] = []
    for key in attribute_order:
        pair_a_b = by_pair[0].get(key, {})
        pair_a_c = by_pair[1].get(key, {}) if len(by_pair) > 1 else {}
        label = str(pair_a_b.get("Attribute") or pair_a_c.get("Attribute") or "").strip()
        assessments = []
        evidence = []
        for slot, row in (("Part B", pair_a_b), ("Part C", pair_a_c)):
            assessment = str(row.get("Assessment") or "").strip()
            if assessment:
                assessments.append(f"{slot}: {assessment}")
            evidence_text = str(row.get("Evidence") or "").strip()
            if evidence_text and evidence_text not in evidence:
                evidence.append(evidence_text)
        rows.append(
            {
                "Attribute": label,
                "Part A": str(pair_a_b.get("Part A") or pair_a_c.get("Part A") or ""),
                "Part B": str(pair_a_b.get("Part B") or ""),
                "Part C": str(pair_a_c.get("Part B") or ""),
                "Assessment": " · ".join(assessments),
                "Evidence": " · ".join(evidence),
            }
        )

    counts = {
        "compatible": sum(int(item.get("counts", {}).get("compatible") or 0) for item in pair_comparisons),
        "material_difference": sum(int(item.get("counts", {}).get("material_difference") or 0) for item in pair_comparisons),
        "needs_data": sum(int(item.get("counts", {}).get("needs_data") or 0) for item in pair_comparisons),
    }
    findings = {str(item.get("finding") or FINDING_NEEDS_DATA) for item in pair_comparisons}
    if FINDING_MATERIAL in findings:
        finding = FINDING_MATERIAL
    elif FINDING_NEEDS_DATA in findings:
        finding = FINDING_NEEDS_DATA
    else:
        finding = FINDING_COMPATIBLE

    first = pair_comparisons[0]
    comparison_result = {
        "part_a": cards[0],
        "part_b": cards[1],
        "part_c": cards[2] if len(cards) > 2 else {},
        "family": first.get("family", "General"),
        "family_display_name": first.get("family_display_name", "General components"),
        "family_mismatch": any(bool(item.get("family_mismatch")) for item in pair_comparisons),
        "finding": finding,
        "engineering_evidence_summary": "Part B and any added Part C are assessed independently against Part A using available evidence.",
        "engineering_evidence_status": "pairwise",
        "counts": counts,
        "rows": rows,
        "supplier_substitute_claim": False,
        "datasheet_identity": first.get("datasheet_identity") or {},
        "review_warnings": list(first.get("review_warnings") or []),
        "notes": [
            "Part B and any added Part C are each compared with Part A.",
            "Missing attributes stay missing; Cadivor does not infer a match.",
            "Datasheet values are used only when the extracted text names the entered manufacturer and exact MPN.",
        ],
    }
    return {
        "status": STATUS_COMPLETED,
        "part_a": parts[0],
        "part_b": parts[1],
        "part_c": parts[2] if len(parts) > 2 else "",
        "part_numbers": parts,
        "comparison": comparison_result,
        "error": "",
    }



def generate_parts_comparison_pdf(comparison: Mapping[str, Any]) -> bytes:
    """Build a concise downloadable PDF using the same user-facing fields as the screen."""
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    part_a = dict(comparison.get("part_a") or {})
    part_b = dict(comparison.get("part_b") or {})
    finding = str(comparison.get("finding") or FINDING_NEEDS_DATA)
    rows = list(comparison.get("rows") or [])

    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=42,
        leftMargin=42,
        topMargin=48,
        bottomMargin=42,
        title=f"Cadivor Parts Comparison: {part_a.get('mpn')} vs {part_b.get('mpn')}",
        author="Cadivor",
    )
    styles = getSampleStyleSheet()
    title = styles["Title"].clone("cp_title")
    title.fontName = "Helvetica-Bold"
    title.fontSize = 18
    title.leading = 22
    title.textColor = colors.HexColor("#0B1220")
    title.alignment = 0
    body = styles["BodyText"].clone("cp_body")
    body.fontName = "Helvetica"
    body.fontSize = 9
    body.leading = 12
    body.textColor = colors.HexColor("#334155")
    section = styles["Heading2"].clone("cp_section")
    section.fontName = "Helvetica-Bold"
    section.fontSize = 12
    section.textColor = colors.HexColor("#0F172A")

    story = [
        Paragraph("Cadivor Parts Comparison", title),
        Spacer(1, 8),
        Paragraph(
            f"<b>Finding:</b> {finding}",
            body,
        ),
        Paragraph(
            str(comparison.get("engineering_evidence_summary") or ""),
            body,
        ),
        Spacer(1, 10),
        Paragraph("Part identity", section),
        Paragraph(
            (
                f"<b>Part A:</b> {part_a.get('mpn') or '—'} · "
                f"{part_a.get('manufacturer') or '—'} · "
                f"{part_a.get('family_display_name') or '—'} · "
                f"Package {part_a.get('package') or '—'} · "
                f"Lifecycle {part_a.get('lifecycle_status') or '—'}"
            ),
            body,
        ),
        Paragraph(
            (
                f"<b>Part B:</b> {part_b.get('mpn') or '—'} · "
                f"{part_b.get('manufacturer') or '—'} · "
                f"{part_b.get('family_display_name') or '—'} · "
                f"Package {part_b.get('package') or '—'} · "
                f"Lifecycle {part_b.get('lifecycle_status') or '—'}"
            ),
            body,
        ),
        Spacer(1, 10),
        Paragraph("Attribute comparison", section),
    ]

    table_data = [["Attribute", "Part A", "Part B", "Assessment", "Evidence"]]
    for row in rows[:40]:
        table_data.append(
            [
                Paragraph(str(row.get("Attribute") or ""), body),
                Paragraph(str(row.get("Part A") or ""), body),
                Paragraph(str(row.get("Part B") or ""), body),
                Paragraph(str(row.get("Assessment") or ""), body),
                Paragraph(str(row.get("Evidence") or ""), body),
            ]
        )
    table = Table(table_data, colWidths=[78, 88, 88, 100, 140])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "Engineering compatibility is separate from supplier substitute relationships. "
            "Missing data was not inferred as a match.",
            body,
        )
    )
    document.build(story)
    return buffer.getvalue()


# Re-export for page/admin gating tests.
__all__ = [
    "FINDING_COMPATIBLE",
    "FINDING_MATERIAL",
    "FINDING_NEEDS_DATA",
    "USER_FACING_COMPARE_COLUMNS",
    "COMPARE_PARTS_PART_A_WIDGET_KEY",
    "COMPARE_PARTS_PART_B_WIDGET_KEY",
    "build_parts_comparison",
    "claim_compare_parts_submit",
    "derive_overall_finding",
    "generate_parts_comparison_pdf",
    "lookup_part_for_compare",
    "map_status_to_assessment",
    "public_part_card",
    "resolve_compare_parts_submitted_mpn",
    "run_compare_parts",
    "user_facing_compare_rows",
    "user_may_view_comparison_diagnostics",
    "user_facing_comparison_rows",
]
