"""Shared two-user (tenant A / tenant B) allow + deny matrix.

Imported by ``test_workspace_isolation`` (file-backed disposable store) and
``test_cutover_disposable_db`` (disposable embedded Postgres) so both backends
prove the exact same contract. This module is not collected by pytest.

Contract (Acceptance D3):
- User B is denied list / read / download / export / update / delete on
  User A's workspace, BOMs, reports, decisions and monitoring records.
- User B can only reach their own records (allowed cases).
- Monitoring GET is read-only; every monitoring write goes through
  ``POST /tools/monitoring/refresh`` (or the explicit acknowledge / preference
  endpoints), and B can never trigger one against A's analysis.
- Nothing here creates a real account or sends email: callers pass JWTs for
  disposable sandbox users only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
FLAT_BOM = ROOT / "tests/fixtures/synthetic_bom_25parts.csv"

EXPORT_FORMATS = ("pdf", "csv", "xlsx")


def _decision_body(analysis_id: str, *, reviewer: str) -> dict[str, Any]:
    return {
        "analysis_id": analysis_id,
        "part_a": "RES10K",
        "part_b": "CAP100U",
        "decision": "hold_for_review",
        "reviewer": reviewer,
        "rationale": "Verify the exact part specifications before release.",
    }


def seed_workspace(
    client: TestClient,
    headers: dict[str, str],
    *,
    owner: str,
    preferences: dict[str, bool],
    bom_path: Path = FLAT_BOM,
) -> dict[str, Any]:
    """Create BOM + report + decision + persisted monitoring for one user."""
    created = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": (bom_path.name, bom_path.read_bytes(), "text/csv")},
        data={
            "project_name": f"{owner} Private Project",
            "bom_name": f"{owner} Private BOM",
            "revision": "A",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    analysis_id = body["analysis_id"]

    decision = client.post(
        "/decision-records",
        headers=headers,
        json=_decision_body(analysis_id, reviewer=f"{owner} reviewer"),
    )
    assert decision.status_code == 201, decision.text

    prefs = client.put(
        "/tools/monitoring/preferences",
        headers=headers,
        json=preferences,
    )
    assert prefs.status_code == 200, prefs.text
    assert {k: prefs.json()["preferences"][k] for k in preferences} == preferences

    # GET is read-only: it must not persist anything. Persist via explicit POST.
    before = client.get("/tools/monitoring/alerts", headers=headers).json()
    assert before["alerts"] == []
    assert before["refresh_history"] == []
    view = client.get(f"/tools/monitoring?analysis_id={analysis_id}", headers=headers)
    assert view.status_code == 200, view.text
    after_get = client.get("/tools/monitoring/alerts", headers=headers).json()
    assert after_get["alerts"] == [], "monitoring GET must not persist alerts"
    assert after_get["refresh_history"] == [], "monitoring GET must not record a refresh"

    refresh = client.post(
        "/tools/monitoring/refresh",
        headers=headers,
        params={"analysis_id": analysis_id},
    )
    assert refresh.status_code == 200, refresh.text
    assert refresh.json()["persisted"] is True
    alerts = client.get("/tools/monitoring/alerts", headers=headers).json()["alerts"]
    assert alerts, "synthetic fixture should persist at least one monitoring alert"

    saved = client.get(f"/reports/{analysis_id}", headers=headers).json()
    return {
        "owner": owner,
        "report_project_name": saved["project_name"],
        "report_bom_name": saved["bom_name"],
        "analysis_id": analysis_id,
        "project_id": body["project_id"],
        "bom_id": body["bom_id"],
        "workspace_id": body["workspace_id"],
        "project_name": f"{owner} Private Project",
        "decision_id": decision.json()["record"]["id"],
        "alert_ids": sorted(a["id"] for a in alerts),
        "alert_count": len(alerts),
        "preferences": prefs.json()["preferences"],
        "csv_export_bytes": client.get(
            f"/reports/{analysis_id}/export/csv", headers=headers
        ).content,
    }


def assert_denied_for_other_user(
    client: TestClient,
    headers: dict[str, str],
    victim: dict[str, Any],
) -> list[dict[str, Any]]:
    """Every probe from the attacker must be denied / empty. Returns a ledger."""
    ledger: list[dict[str, Any]] = []
    analysis_id = victim["analysis_id"]
    project_id = victim["project_id"]

    def deny(name: str, response: Any, *codes: int) -> None:
        allowed = codes or (404,)
        ledger.append({"case": name, "status": response.status_code, "expected": list(allowed)})
        assert response.status_code in allowed, (
            f"{name}: expected {allowed}, got {response.status_code}: {response.text[:200]}"
        )
        body = response.text
        for secret in (victim["project_name"], victim["decision_id"]):
            assert secret not in body, f"{name}: leaked {secret!r}"

    def empty(name: str, condition: bool) -> None:
        ledger.append({"case": name, "status": 200, "expected": ["empty"]})
        assert condition, f"{name}: attacker saw victim data"

    # --- list ---
    reports = client.get("/reports", headers=headers)
    empty("list reports", reports.status_code == 200 and analysis_id not in {
        r["id"] for r in reports.json()["reports"]
    })
    projects = client.get("/projects", headers=headers)
    empty("list projects", projects.status_code == 200 and project_id not in {
        p["id"] for p in projects.json()["projects"]
    })
    home = client.get("/workspace/home", headers=headers)
    assert home.status_code == 200
    home_body = home.json()
    assert home_body["workspace_id"] != victim["workspace_id"]
    empty("list workspace home", victim["project_name"] not in home.text)
    decisions = client.get("/decision-records", headers=headers)
    empty("list decisions", decisions.status_code == 200 and victim["decision_id"] not in {
        r["id"] for r in decisions.json()["records"]
    })
    deny(
        "list decisions scoped to victim analysis",
        client.get("/decision-records", headers=headers, params={"analysis_id": analysis_id}),
    )
    alerts = client.get("/tools/monitoring/alerts", headers=headers)
    empty("list monitoring alerts", alerts.status_code == 200 and not (
        set(victim["alert_ids"]) & {a["id"] for a in alerts.json()["alerts"]}
    ))
    scoped_alerts = client.get(
        "/tools/monitoring/alerts", headers=headers, params={"analysis_id": analysis_id}
    )
    empty(
        "list monitoring alerts scoped to victim analysis",
        scoped_alerts.status_code == 200 and scoped_alerts.json()["alerts"] == [],
    )
    empty(
        "monitoring refresh history",
        all(
            str(row.get("analysis_id") or "") != analysis_id
            for row in alerts.json()["refresh_history"]
        ),
    )
    prefs = client.get("/tools/monitoring/preferences", headers=headers)
    own_before = prefs.json()["preferences"]
    empty(
        "monitoring preferences are per-workspace",
        prefs.status_code == 200 and own_before != victim["preferences"],
    )

    # --- read ---
    deny("read report", client.get(f"/reports/{analysis_id}", headers=headers))
    deny(
        "read monitoring (GET, read-only)",
        client.get("/tools/monitoring", headers=headers, params={"analysis_id": analysis_id}),
    )
    for path in (
        "/tools/procurement",
        "/tools/design-impact",
        "/tools/cost-optimization",
        "/tools/detailed-risk",
        "/compliance/rohs",
    ):
        deny(f"read {path}", client.get(path, headers=headers, params={"analysis_id": analysis_id}))
    deny(
        "read supply-risk",
        client.post("/tools/supply-risk", headers=headers, json={"analysis_id": analysis_id}),
    )
    deny(
        "read compare-parts",
        client.post(
            "/tools/compare-parts",
            headers=headers,
            json={"part_a": "RES10K", "part_b": "CAP100U", "analysis_id": analysis_id},
        ),
    )

    # --- download / export ---
    deny("download legacy csv", client.get(f"/reports/{analysis_id}/export.csv", headers=headers))
    for fmt in EXPORT_FORMATS:
        response = client.get(f"/reports/{analysis_id}/export/{fmt}", headers=headers)
        deny(f"export {fmt}", response)
        assert response.headers.get("content-disposition") is None, f"export {fmt} leaked a file"

    # --- update ---
    deny(
        "rename project",
        client.patch(f"/projects/{project_id}", headers=headers, json={"name": "Hijacked"}),
    )
    deny(
        "record decision on victim analysis",
        client.post(
            "/decision-records",
            headers=headers,
            json=_decision_body(analysis_id, reviewer="Intruder"),
        ),
    )
    deny(
        "monitoring refresh (POST) victim analysis",
        client.post("/tools/monitoring/refresh", headers=headers, params={"analysis_id": analysis_id}),
    )
    deny(
        "monitoring refresh dry-run victim analysis",
        client.post(
            "/tools/monitoring/refresh",
            headers=headers,
            params={"analysis_id": analysis_id, "dry_run": "1"},
        ),
    )
    for alert_id in victim["alert_ids"][:3]:
        deny(
            "acknowledge victim alert",
            client.post(
                "/tools/monitoring/acknowledge", headers=headers, json={"alert_id": alert_id}
            ),
        )
    # /notify requires an alert_id owned by the caller's workspace. A foreign id
    # must 404 and never deliver or echo the victim's alert.
    notify = client.post(
        "/tools/monitoring/notify",
        headers=headers,
        json={"alert_id": victim["alert_ids"][0]},
    )
    ledger.append({"case": "notify on victim alert", "status": notify.status_code, "expected": [404]})
    assert notify.status_code == 404, notify.text[:200]
    for secret in (victim["project_name"], victim["decision_id"], *victim["alert_ids"]):
        assert secret not in notify.text, "notify leaked victim data"
    # Attacker's own preference write (idempotent here) must never touch the victim.
    own_prefs = client.put(
        "/tools/monitoring/preferences", headers=headers, json=own_before
    )
    assert own_prefs.status_code == 200
    assert own_prefs.json()["preferences"] == own_before

    # --- delete ---
    deny("delete report", client.delete(f"/reports/{analysis_id}", headers=headers))
    deny("delete project", client.delete(f"/projects/{project_id}", headers=headers))

    # --- forged workspace hints are never trusted ---
    forged = client.get(
        "/reports",
        headers={**headers, "X-Workspace-Id": victim["workspace_id"]},
        params={"workspace_id": victim["workspace_id"]},
    )
    empty(
        "forged workspace_id/X-Workspace-Id ignored",
        forged.status_code == 200
        and analysis_id not in {r["id"] for r in forged.json()["reports"]}
        and forged.json()["workspace_id"] != victim["workspace_id"],
    )
    return ledger


def assert_owner_still_has_everything(
    client: TestClient,
    headers: dict[str, str],
    owner: dict[str, Any],
) -> list[dict[str, Any]]:
    """Allowed cases for the owner, run after the attacker's denied probes."""
    ledger: list[dict[str, Any]] = []
    analysis_id = owner["analysis_id"]

    def allow(name: str, response: Any) -> Any:
        ledger.append({"case": name, "status": response.status_code, "expected": [200]})
        assert response.status_code == 200, f"{name}: {response.status_code} {response.text[:200]}"
        return response

    report = allow("owner read report", client.get(f"/reports/{analysis_id}", headers=headers)).json()
    assert report["workspace_id"] == owner["workspace_id"]
    assert report["project_name"] == owner["report_project_name"], "attacker rename must not apply"
    assert report["bom_name"] == owner["report_bom_name"]
    assert {r["id"] for r in allow("owner list reports", client.get("/reports", headers=headers)).json()["reports"]} == {analysis_id}
    owned_projects = allow("owner list projects", client.get("/projects", headers=headers)).json()["projects"]
    assert [p["id"] for p in owned_projects] == [owner["project_id"]]
    assert owned_projects[0]["name"] == owner["project_name"], "attacker rename must not apply"
    records = allow(
        "owner list decisions",
        client.get("/decision-records", headers=headers, params={"analysis_id": analysis_id}),
    ).json()["records"]
    assert [r["id"] for r in records] == [owner["decision_id"]], "no foreign/duplicate decisions"
    alerts = allow("owner list alerts", client.get("/tools/monitoring/alerts", headers=headers)).json()["alerts"]
    assert sorted(a["id"] for a in alerts) == owner["alert_ids"]
    assert not any(a.get("acknowledged") for a in alerts), "attacker acknowledge must not apply"
    prefs = allow("owner preferences", client.get("/tools/monitoring/preferences", headers=headers)).json()["preferences"]
    assert prefs == owner["preferences"], "attacker preference probe must not apply"
    allow(
        "owner read monitoring (GET)",
        client.get(f"/tools/monitoring?analysis_id={analysis_id}", headers=headers),
    )
    for path in ("/tools/procurement", "/tools/detailed-risk", "/tools/design-impact"):
        allow(f"owner read {path}", client.get(path, headers=headers, params={"analysis_id": analysis_id}))
    for fmt in EXPORT_FORMATS:
        response = allow(f"owner export {fmt}", client.get(f"/reports/{analysis_id}/export/{fmt}", headers=headers))
        assert response.headers["content-disposition"].startswith("attachment;")
    assert (
        client.get(f"/reports/{analysis_id}/export/csv", headers=headers).content
        == owner["csv_export_bytes"]
    ), "owner CSV export bytes changed after attacker probes"
    allow("owner legacy csv", client.get(f"/reports/{analysis_id}/export.csv", headers=headers))
    return ledger


def assert_unauthenticated_denied(client: TestClient, victim: dict[str, Any]) -> None:
    analysis_id = victim["analysis_id"]
    for method, path in (
        ("get", "/reports"),
        ("get", f"/reports/{analysis_id}"),
        ("get", f"/reports/{analysis_id}/export/pdf"),
        ("get", f"/reports/{analysis_id}/export/csv"),
        ("get", f"/reports/{analysis_id}/export/xlsx"),
        ("get", "/projects"),
        ("get", "/decision-records"),
        ("get", "/tools/monitoring"),
        ("get", "/tools/monitoring/alerts"),
        ("post", "/tools/monitoring/refresh"),
        ("delete", f"/reports/{analysis_id}"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 401, f"{method.upper()} {path}: {response.status_code}"


#: Distinct per-owner monitoring preferences so bleed-through is detectable.
PREFERENCES_A = {"email_alerts": True, "lifecycle": True, "availability": False, "risk": False}
PREFERENCES_B = {"email_alerts": False, "lifecycle": False, "availability": True, "risk": True}


def assert_other_user_only_sees_own(
    client: TestClient,
    headers: dict[str, str],
    other: dict[str, Any],
) -> list[dict[str, Any]]:
    """Allowed cases for User B against User B's own freshly seeded workspace."""
    ledger: list[dict[str, Any]] = []
    analysis_id = other["analysis_id"]

    def allow(name: str, response: Any, *codes: int) -> Any:
        ok = codes or (200,)
        ledger.append({"case": name, "status": response.status_code, "expected": list(ok)})
        assert response.status_code in ok, f"{name}: {response.status_code} {response.text[:200]}"
        return response

    assert {r["id"] for r in allow("B list reports", client.get("/reports", headers=headers)).json()["reports"]} == {analysis_id}
    assert allow("B read report", client.get(f"/reports/{analysis_id}", headers=headers)).json()["workspace_id"] == other["workspace_id"]
    for fmt in EXPORT_FORMATS:
        allow(f"B export {fmt}", client.get(f"/reports/{analysis_id}/export/{fmt}", headers=headers))
    records = allow("B list decisions", client.get("/decision-records", headers=headers)).json()["records"]
    assert [r["id"] for r in records] == [other["decision_id"]]
    alerts = allow("B list alerts", client.get("/tools/monitoring/alerts", headers=headers)).json()["alerts"]
    assert sorted(a["id"] for a in alerts) == other["alert_ids"]
    ack = allow(
        "B acknowledge own alert",
        client.post(
            "/tools/monitoring/acknowledge", headers=headers, json={"alert_id": other["alert_ids"][0]}
        ),
    ).json()
    assert ack["alert"]["acknowledged"] is True
    allow(
        "B rename own project",
        client.patch(f"/projects/{other['project_id']}", headers=headers, json={"name": "B Renamed"}),
    )
    allow("B delete own report", client.delete(f"/reports/{analysis_id}", headers=headers))
    allow("B deleted report is gone", client.get(f"/reports/{analysis_id}", headers=headers), 404)
    allow("B delete own project", client.delete(f"/projects/{other['project_id']}", headers=headers))
    return ledger
