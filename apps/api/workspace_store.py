"""Migration workspace store: dedicated Postgres or ephemeral local file.

Tenant-scoped by workspace_id on every project / BOM / revision / analysis /
report path.

Deployed services use CADIVOR_MIGRATION_DATABASE_URL. Its Postgres database is
separate from the Streamlit app's saved-BOM data. File storage is for local
preview/tests only — never a silent deployed fallback.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from apps.api.json_safe import json_safe
from src.saved_bom_project import (
    DEFAULT_WORKSPACE_PROJECT,
    analysis_title_for_upload,
)
from apps.api.report_visibility import customer_visible_analyses, customer_visible_projects

_LOCK = threading.RLock()
_DEFAULT_PATH = Path(
    os.environ.get(
        "CADIVOR_MIGRATION_STORE",
        str(
            Path(__file__).resolve().parents[2]
            / ".evidence"
            / "nextjs_migration"
            / "workspace_store.json"
        ),
    )
)


class WorkspaceAccessError(LookupError):
    """Raised when a record exists but belongs to another workspace."""


class PersistenceNotConfiguredError(RuntimeError):
    """Deployed services require the migration database; file fallback disabled."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict[str, Any]:
    return {
        "version": 2,
        "projects": {},
        "boms": {},
        "revisions": {},
        "analyses": {},
        "reports": {},
        "decision_records": {},
        "decision_record_shares": {},
        "decision_record_approvers": {},
        "developer_webhooks": {},
        "developer_webhook_deliveries": {},
        "procurement_quotes": {},
    }


def migration_database_url() -> str:
    """Dedicated migration database; never use Supabase data-store credentials."""
    return (os.environ.get("CADIVOR_MIGRATION_DATABASE_URL") or "").strip()


def allow_ephemeral_file_store() -> bool:
    """File store is limited to local preview/tests, not deployed fallback."""
    if (os.environ.get("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE") or "").strip() == "1":
        return True
    # Local / CI without Railway: ephemeral file store is explicit preview mode.
    if not (os.environ.get("RAILWAY_ENVIRONMENT") or "").strip():
        return True
    return False


class WorkspaceStore:
    backend = "file"
    durable_across_redeploy = False

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH
        self._data = _empty()
        self.load()

    def load(self) -> None:
        with _LOCK:
            if self.path.exists():
                try:
                    self._data = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    self._data = _empty()
            else:
                self._data = _empty()

    def save(self) -> None:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def clear(self) -> None:
        with _LOCK:
            self._data = _empty()
            self.save()

    def _require_workspace(self, workspace_id: str) -> str:
        wid = str(workspace_id or "").strip()
        if not wid:
            raise ValueError("workspace_id is required")
        return wid

    def _project_in_workspace(self, project_id: str, workspace_id: str) -> bool:
        project = self._data["projects"].get(project_id) or {}
        return project.get("workspace_id") == workspace_id

    def _bom_workspace_id(self, bom_id: str) -> str | None:
        bom = self._data["boms"].get(bom_id) or {}
        if bom.get("workspace_id"):
            return str(bom["workspace_id"])
        project = self._data["projects"].get(bom.get("project_id") or "") or {}
        return project.get("workspace_id")

    def upsert_analysis_report(
        self,
        report: dict[str, Any],
        *,
        workspace_id: str,
        project_name: str | None = None,
        bom_name: str | None = None,
        revision: str | None = None,
    ) -> dict[str, Any]:
        """Save analysis + report scoped to workspace_id."""
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            filename = str(report.get("filename") or "bom.csv")
            project = (project_name or "").strip() or DEFAULT_WORKSPACE_PROJECT
            bom = (bom_name or "").strip() or filename
            rev = (revision or "").strip() or "A"
            title = analysis_title_for_upload(project, bom)

            project_id = self._ensure_project(project, wid)
            bom_id = self._ensure_bom(project_id, bom, filename, wid)
            revision_id = self._ensure_revision(bom_id, rev, wid)

            analysis_id = str(report.get("id") or uuid.uuid4())
            report = dict(json_safe(report))
            report["id"] = analysis_id
            report["analysis_id"] = analysis_id
            report["project_id"] = project_id
            report["project_name"] = title
            report["bom_id"] = bom_id
            report["bom_name"] = bom
            report["revision_id"] = revision_id
            report["revision"] = rev
            report["workspace_id"] = wid
            report["persisted"] = True
            report["persistence"] = "migration-workspace-store"

            analysis = {
                "id": analysis_id,
                "analysis_id": analysis_id,
                "workspace_id": wid,
                "project_id": project_id,
                "bom_id": bom_id,
                "revision_id": revision_id,
                "project_name": title,
                "bom_name": bom,
                "revision": rev,
                "filename": filename,
                "created_at": report.get("created_at") or _now(),
                "updated_at": _now(),
                "health_score": report.get("health_score"),
                "health_status": report.get("health_status"),
                "summary_message": report.get("summary_message"),
                "needs_verification_count": report.get("needs_verification_count"),
                "high_risk_count": report.get("high_risk_count"),
                "medium_risk_count": report.get("medium_risk_count"),
                "low_risk_count": report.get("low_risk_count"),
                "total_parts": report.get("total_parts"),
                "mode": report.get("mode"),
                "has_hierarchy": bool((report.get("hierarchy") or {}).get("has_hierarchy")),
                "top_rolled_risk": ((report.get("hierarchy") or {}).get("top_level") or {}).get(
                    "rolled_risk_level"
                ),
            }
            self._data["analyses"][analysis_id] = analysis
            self._data["reports"][analysis_id] = report
            self._data["revisions"][revision_id]["latest_analysis_id"] = analysis_id
            self._data["revisions"][revision_id]["updated_at"] = _now()
            self._data["boms"][bom_id]["latest_analysis_id"] = analysis_id
            self._data["boms"][bom_id]["updated_at"] = _now()
            self._data["projects"][project_id]["updated_at"] = _now()
            self.save()
            return report

    def _ensure_project(self, name: str, workspace_id: str) -> str:
        for pid, row in self._data["projects"].items():
            if row.get("name") == name and row.get("workspace_id") == workspace_id:
                return pid
        pid = str(uuid.uuid4())
        self._data["projects"][pid] = {
            "id": pid,
            "name": name,
            "workspace_id": workspace_id,
            "created_at": _now(),
            "updated_at": _now(),
        }
        return pid

    def _ensure_bom(
        self, project_id: str, name: str, filename: str, workspace_id: str
    ) -> str:
        for bid, row in self._data["boms"].items():
            if (
                row.get("project_id") == project_id
                and row.get("name") == name
                and row.get("workspace_id") == workspace_id
            ):
                return bid
        bid = str(uuid.uuid4())
        self._data["boms"][bid] = {
            "id": bid,
            "project_id": project_id,
            "workspace_id": workspace_id,
            "name": name,
            "filename": filename,
            "created_at": _now(),
            "updated_at": _now(),
            "latest_analysis_id": None,
        }
        return bid

    def _ensure_revision(self, bom_id: str, revision: str, workspace_id: str) -> str:
        for rid, row in self._data["revisions"].items():
            if (
                row.get("bom_id") == bom_id
                and row.get("revision") == revision
                and row.get("workspace_id") == workspace_id
            ):
                return rid
        rid = str(uuid.uuid4())
        self._data["revisions"][rid] = {
            "id": rid,
            "bom_id": bom_id,
            "workspace_id": workspace_id,
            "revision": revision,
            "created_at": _now(),
            "updated_at": _now(),
            "latest_analysis_id": None,
        }
        return rid

    def get_report(
        self, analysis_id: str, *, workspace_id: str
    ) -> dict[str, Any] | None:
        wid = self._require_workspace(workspace_id)
        # RLock: load() re-enters the same lock safely. Upsert always save()s
        # before releasing, so a reload cannot observe a half-written report.
        with _LOCK:
            # Reload so another process write on a shared file is visible.
            self.load()
            report = self._data["reports"].get(analysis_id)
            if not report:
                return None
            if report.get("workspace_id") != wid:
                raise WorkspaceAccessError(
                    f"analysis {analysis_id} is not in workspace {wid}"
                )
            return dict(report)

    def update_analysis_health(
        self,
        analysis_id: str,
        *,
        workspace_id: str,
        health: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Persist a recalculated health summary without rewriting BOM identity."""
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            self.load()
            report = self._data["reports"].get(analysis_id)
            analysis = self._data["analyses"].get(analysis_id)
            record = report or analysis
            if not record:
                return None
            if record.get("workspace_id") != wid:
                raise WorkspaceAccessError(
                    f"analysis {analysis_id} is not in workspace {wid}"
                )
            for field, value in health.items():
                if report is not None:
                    report[field] = value
                if analysis is not None:
                    analysis[field] = value
            self.save()
            return dict(report or analysis or {})

    def list_reports(self, *, workspace_id: str) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            self.load()
            rows = []
            for row in self._data["analyses"].values():
                if row.get("workspace_id") != wid:
                    continue
                item = dict(row)
                project = self._data["projects"].get(str(row.get("project_id") or "")) or {}
                item["project_label"] = project.get("name") or row.get("project_name")
                saved_report = self._data["reports"].get(str(row.get("id") or "")) or {}
                item["summary_message"] = saved_report.get("summary_message") or row.get("summary_message")
                item["needs_verification_count"] = saved_report.get(
                    "needs_verification_count", row.get("needs_verification_count")
                )
                rows.append(item)
            return sorted(
                rows, key=lambda row: str(row.get("created_at") or ""), reverse=True
            )

    def list_monitoring_analyses(self) -> list[dict[str, Any]]:
        """Return saved analysis scopes for the scheduler, without report contents."""
        with _LOCK:
            return [
                {"workspace_id": str(row.get("workspace_id") or ""),
                 "analysis_id": str(row.get("id") or ""),
                 "total_parts": int(row.get("total_parts") or len(row.get("parts") or []))}
                for row in self._data.get("analyses", {}).values()
                if row.get("workspace_id") and row.get("id")
            ]

    def create_decision_record(
        self, record: dict[str, Any], *, workspace_id: str
    ) -> dict[str, Any]:
        """Persist a human decision and its comparison snapshot by workspace."""
        wid = self._require_workspace(workspace_id)
        analysis_id = str(record.get("analysis_id") or "").strip()
        if analysis_id and not self.get_report(analysis_id, workspace_id=wid):
            raise WorkspaceAccessError(f"analysis {analysis_id} was not found")
        with _LOCK:
            saved = dict(record)
            decision_id = str(saved.get("decision_id") or uuid.uuid4())
            saved.update(
                {
                    "id": decision_id,
                    "decision_id": decision_id,
                    "workspace_id": wid,
                    "created_at": str(saved.get("created_at") or _now()),
                }
            )
            self._data.setdefault("decision_records", {})[decision_id] = saved
            self.save()
            return dict(saved)

    def list_decision_records(
        self, *, workspace_id: str, analysis_id: str | None = None
    ) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        aid = str(analysis_id or "").strip()
        with _LOCK:
            rows = []
            for record in self._data.setdefault("decision_records", {}).values():
                if record.get("workspace_id") != wid:
                    continue
                if aid and str(record.get("analysis_id") or "") != aid:
                    continue
                rows.append(dict(record))
            return sorted(
                rows, key=lambda row: str(row.get("created_at") or ""), reverse=True
            )

    def create_developer_webhook(self, row: dict[str, Any]) -> dict[str, Any]:
        wid = self._require_workspace(str(row.get("workspace_id") or ""))
        webhook_id = str(row.get("id") or uuid.uuid4())
        saved = dict(json_safe(row))
        saved.update({"id": webhook_id, "workspace_id": wid, "created_at": _now(), "updated_at": _now()})
        with _LOCK:
            self._data.setdefault("developer_webhooks", {})[webhook_id] = saved
            self.save()
        return dict(saved)

    def list_developer_webhooks(self, workspace_id: str) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            rows = [
                dict(row)
                for row in self._data.setdefault("developer_webhooks", {}).values()
                if str(row.get("workspace_id") or "") == wid
            ]
        return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)

    def get_developer_webhook(self, workspace_id: str, webhook_id: str) -> dict[str, Any] | None:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            row = dict(self._data.setdefault("developer_webhooks", {}).get(str(webhook_id or "")) or {})
        return row if row and str(row.get("workspace_id") or "") == wid else None

    def delete_developer_webhook(self, workspace_id: str, webhook_id: str) -> bool:
        row = self.get_developer_webhook(workspace_id, webhook_id)
        if not row or row.get("active") is not True:
            return False
        with _LOCK:
            self._data["developer_webhooks"][str(webhook_id)] = {**row, "active": False, "updated_at": _now()}
            for delivery in self._data.setdefault("developer_webhook_deliveries", {}).values():
                if str(delivery.get("we