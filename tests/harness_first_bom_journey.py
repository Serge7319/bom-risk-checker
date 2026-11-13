#!/usr/bin/env python3
"""Sprint 74 — deterministic first BOM journey harness."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_first_bom_journey import run_first_bom_journey


JOURNEY_COLUMNS = ("Part Number", "Manufacturer", "Description", "Qty")
JOURNEY_ROWS = (
    ("LM358DR", "Texas Instruments", "Op-amp \u00b5-power", 3),
    ("GRM188R71H104KA93D", "Murata \u00c9lectronique", "100nF \u00abX7R\u00bb", 10),
    ("LM358DR", "Texas Instruments", "Op-amp \u00b5-power", 2),  # duplicate -> qty 5
    ("RC0603FR-0710KL", "Yageo", "10k resistor, 1%", 25),
)


def synthetic_journey_bom() -> tuple[bytes, dict[str, dict[str, Any]]]:
    """UTF-8-with-BOM CSV whose headers need mapping (Part Number -> mpn, Qty -> quantity)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(JOURNEY_COLUMNS)
    writer.writerows(JOURNEY_ROWS)
    expected: dict[str, dict[str, Any]] = {}
    for mpn, manufacturer, description, quantity in JOURNEY_ROWS:
        entry = expected.setdefault(
            mpn, {"manufacturer": manufacturer, "description": description, "qty": 0}
        )
        entry["qty"] += quantity
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8"), expected


def run_repeat_upload_journey(
    client: Any,
    *,
    login: Callable[[str], dict[str, str]],
    other_login: Callable[[], dict[str, str]],
    restart: Callable[[], None],
) -> dict[str, Any]:
    """Repeat-upload journey under disposable auth; returns a sanitized ledger.

    upload -> map -> validate -> analyze -> save -> navigate away -> (repeat
    upload) -> reload (simulated process restart + fresh sign-in) -> reopen.
    Contains no tokens, emails, or absolute paths.
    """
    from apps.api import monitoring_store

    payload, expected = synthetic_journey_bom()
    steps: list[dict[str, Any]] = []

    def record(step: str, **detail: Any) -> None:
        steps.append({"step": step, "ok": True, **detail})

    headers = login("sign-in")
    record("sign_in", auth="disposable-sandbox-jwt")

    def upload(revision: str) -> dict[str, Any]:
        files = {"file": ("repeat-upload-bom.csv", payload, "text/csv")}
        validated = client.post("/boms/validate", headers=headers, files=files)
        assert validated.status_code == 200, validated.text
        preview = validated.json()
        mapping = {c["source"]: c["normalized"] for c in preview["detected_columns"]}
        assert mapping["Part Number"] == "mpn" and mapping["Qty"] == "quantity", mapping
        assert preview["can_analyze"] is True and preview["errors"] == []
        assert preview["row_count"] == len(JOURNEY_ROWS)
        assert preview["unique_part_count"] == len(expected)
        record(f"map_rev_{revision}", mapping={k: mapping[k] for k in ("Part Number", "Qty")})
        record(
            f"validate_rev_{revision}",
            can_analyze=True,
            source_rows=preview["row_count"],
            unique_parts=preview["unique_part_count"],
        )
        analyzed = client.post(
            "/boms/analyze",
            headers=headers,
            files=files,
            data={"project_name": "Repeat Upload Journey", "bom_name": "Journey BOM", "revision": revision},
        )
        assert analyzed.status_code == 200, analyzed.text
        record_ = analyzed.json()
        assert record_["persisted"] is True and record_["revision"] == revision
        record(f"analyze_rev_{revision}", status=200, total_parts=record_["total_parts"], persisted=True)
        return record_

    def snapshot(analysis_id: str, hdrs: dict[str, str]) -> dict[str, Any]:
        response = client.get(f"/reports/{analysis_id}", headers=hdrs)
        assert response.status_code == 200, response.text
        return response.json()

    def assert_matches_source(report: dict[str, Any]) -> None:
        parts = report["parts"]
        mpns = [str(p["MPN"]) for p in parts]
        assert len(mpns) == len(set(mpns)) == len(expected), mpns
        for part in parts:
            want = expected[str(part["MPN"])]
            assert part["Manufacturer"] == want["manufacturer"]
            assert part["Description"] == want["description"]
            assert int(part["Quantity"]) == want["qty"]

    first = upload("A")
    first_id = first["analysis_id"]
    saved_first = snapshot(first_id, headers)
    assert_matches_source(saved_first)
    listed = client.get("/reports", headers=headers).json()["reports"]
    assert first_id in {r["id"] for r in listed}
    record("save", analysis_id_is_uuid=len(first_id) == 36, reopened_in_session=True, parts=len(saved_first["parts"]))

    # Navigate away: other workspace pages (read-only GETs), then monitoring GET.
    history_before = monitoring_store.list_refresh_history(first["workspace_id"])
    alerts_before = monitoring_store.list_alerts(first["workspace_id"])
    visited = {}
    for label, path in (
        ("workspace_home", "/workspace/home"),
        ("projects", "/projects"),
        ("procurement", f"/tools/procurement?analysis_id={first_id}"),
        ("monitoring_get", f"/tools/monitoring?analysis_id={first_id}"),
        ("reports_list", "/reports"),
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, f"{label}: {response.text[:160]}"
        visited[label] = response.status_code
    assert monitoring_store.list_refresh_history(first["workspace_id"]) == history_before
    assert monitoring_store.list_alerts(first["workspace_id"]) == alerts_before
    record("navigate_away", pages=visited, monitoring_get_wrote_nothing=True)

    # Repeat upload of the same file as a new revision of the same BOM.
    second = upload("B")
    assert second["analysis_id"] != first_id
    assert second["project_id"] == first["project_id"] and second["bom_id"] == first["bom_id"]
    saved_second = snapshot(second["analysis_id"], headers)
    assert_matches_source(saved_second)
    assert [p["MPN"] for p in saved_second["parts"]] == [p["MPN"] for p in saved_first["parts"]]
    record("repeat_upload", same_project=True, same_bom=True, new_analysis=True, revisions=["A", "B"])

    export_before = client.get(f"/reports/{first_id}/export/csv", headers=headers).content
    pre_reload = {first_id: saved_first, second["analysis_id"]: saved_second}

    # Reload: drop process-local caches, reopen storage from disk, sign in again.
    restart()
    headers = login("sign-in-after-reload")
    listed = {r["id"]: r for r in client.get("/reports", headers=headers).json()["reports"]}
    assert {first_id, second["analysis_id"]} <= set(listed)
    assert {listed[first_id]["revision"], listed[second["analysis_id"]]["revision"]} == {"A", "B"}
    projects = client.get("/projects", headers=headers).json()["projects"]
    assert len([p for p in projects if p["id"] == first["project_id"]]) == 1
    record("reload", process_cache_cleared=True, storage_reopened=True, new_session=True, reports_listed=len(listed))

    # Reopen: byte-for-byte identical saved report, matching the source BOM.
    for analysis_id, before in pre_reload.items():
        after = snapshot(analysis_id, headers)
        assert after == before, f"report {analysis_id} changed across reload"
        assert_matches_source(after)
    export_after = client.get(f"/reports/{first_id}/export/csv", headers=headers).content
    assert export_after == export_before
    rows = list(csv.DictReader(io.StringIO(export_after.decode("utf-8-sig"), newline="")))
    assert len(rows) == len(expected)
    record("reopen_report", identical_to_pre_reload=True, parts=len(expected), csv_export_stable=True, csv_rows=len(rows))

    other = other_login()
    assert client.get(f"/reports/{first_id}", headers=other).status_code == 404
    record("second_user_denied", status=404)
    return {"ok": True, "boms": {"parts": len(expected), "source_rows": len(JOURNEY_ROWS)}, "steps": steps}


def _disposable_journey() -> dict[str, Any]:
    """Run the journey against a throwaway file store + sandbox auth (no network, no email)."""
    from starlette.testclient import TestClient

    from apps.api import synthetic_analyze, workspace_store
    from apps.api.main import app
    from apps.api.sandbox_auth import reset_auth_store_for_tests
    from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS

    env = {
        "CADIVOR_SANDBOX_AUTH_SECRET": "journey-disposable-secret",
        "CADIVOR_ALLOW_EPHEMERAL_FILE_STORE": "1",
        "CADIVOR_ALLOW_SANDBOX_JWT": "1",
    }
    removed = ("CADIVOR_MIGRATION_DATABASE_URL", "RAILWAY_ENVIRONMENT", "CADIVOR_FORCE_PRODUCTION_AUTH", "CADIVOR_MONITORING_EMAIL_ENABLED")
    saved_env = {k: os.environ.get(k) for k in (*env, *removed)}
    os.environ.update(env)
    for key in removed:
        os.environ.pop(key, None)
    try:
        with tempfile.TemporaryDirectory(prefix="cadivor-journey-") as tmp:
            store_path = Path(tmp) / "store.json"
            workspace_store.reset_store_for_tests(store_path)
            reset_auth_store_for_tests(Path(tmp) / "auth.json", accounts=SANDBOX_SEED_USERS)
            synthetic_analyze._REPORTS.clear()
            client = TestClient(app)

            def _login(index: int) -> dict[str, str]:
                user = SANDBOX_SEED_USERS[index]
                res = client.post("/auth/login", json={"email": user["email"], "password": user["password"]})
                assert res.status_code == 200, res.text
                return {"Authorization": f"Bearer {res.json()['access_token']}"}

            def restart() -> None:
                synthetic_analyze._REPORTS.clear()
                workspace_store._STORE = workspace_store.WorkspaceStore(store_path)

            return run_repeat_upload_journey(
                client,
                login=lambda _label: _login(0),
                other_login=lambda: _login(1),
                restart=restart,
            )
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repeat-upload",
        action="store_true",
        help="Run only the repeat-upload save/reload/reopen journey (Acceptance D1).",
    )
    args = parser.parse_args()
    if args.repeat_upload:
        try:
            result = _disposable_journey()
        except AssertionError as exc:
            print(json.dumps({"ok": False, "error": "AssertionError", "message": str(exc)[:300]}, indent=2))
            return 1
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    scenarios = {
        "valid_csv": [{"mpn": "LM358", "quantity": 10}],
        "empty_bom": [],
        "missing_mpn_column": [{"quantity": 1}],
        "degraded_supplier": [{"mpn": "LM358", "quantity": 1}],
    }

    report = {}

    try:
        report["valid_csv"] = run_first_bom_journey(bom_rows=scenarios["valid_csv"])
    except Exception as exc:
        report["valid_csv"] = {"ok": False, "error": type(exc).__name__}

    try:
        run_first_bom_journey(bom_rows=scenarios["empty_bom"])
        report["empty_bom"] = {"ok": True}
    except ValueError as exc:
        report["empty_bom"] = {"ok": False, "stage": "validation", "message": str(exc)}
    except Exception as exc:
        report["empty_bom"] = {"ok": False, "error": type(exc).__name__}

    try:
        from src.bom_parser import normalize_bom_columns, validate_bom
        import pandas as pd

        df = pd.DataFrame(scenarios["missing_mpn_column"])
        df = normalize_bom_columns(df)
        validate_bom(df)
        report["missing_mpn_column"] = {"ok": True}
    except ValueError as exc:
        report["missing_mpn_column"] = {"ok": False, "stage": "validation", "message": str(exc)}

    report["degraded_supplier"] = run_first_bom_journey(
        bom_rows=scenarios["degraded_supplier"],
        supplier_lookup=lambda part: {
            "manufacturer_part_number": part,
            "stock_total": 0,
            "supplier_count": 0,
            "lifecycle_status": "Unknown",
            "supplier_data_verified": False,
            "source": "No supplier match",
        },
    )

    print(json.dumps(report, indent=2, sort_keys=True))
    failed = [name for name, payload in report.items() if not payload.get("ok", False)]
    return 1 if failed and failed != ["empty_bom", "missing_mpn_column"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
