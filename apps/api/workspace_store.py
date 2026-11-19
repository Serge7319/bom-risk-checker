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
from datetime import datetime, timezone
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

    def list_reports(self, *, workspace_id: str) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            self.load()
            rows = [
                dict(row)
                for row in self._data["analyses"].values()
                if row.get("workspace_id") == wid
            ]
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

    def create_decision_record_share(
        self,
        *,
        workspace_id: str,
        decision_record_id: str,
        token_hash: str,
        created_by: str,
        expires_at: str,
    ) -> None:
        wid = self._require_workspace(workspace_id)
        record_id = str(decision_record_id or "").strip()
        if not any(
            str(row.get("id") or row.get("decision_id") or "") == record_id
            for row in self.list_decision_records(workspace_id=wid)
        ):
            raise WorkspaceAccessError(f"decision {record_id} was not found")
        with _LOCK:
            self._data.setdefault("decision_record_shares", {})[token_hash] = {
                "token_hash": token_hash,
                "workspace_id": wid,
                "decision_record_id": record_id,
                "created_by": str(created_by or ""),
                "created_at": _now(),
                "expires_at": expires_at,
                "revoked_at": None,
            }
            self.save()

    def get_decision_record_share(self, token_hash: str) -> dict[str, Any] | None:
        candidate = str(token_hash or "").strip()
        with _LOCK:
            share = dict(
                self._data.setdefault("decision_record_shares", {}).get(candidate) or {}
            )
            if not share or share.get("revoked_at"):
                return None
            try:
                expires = datetime.fromisoformat(
                    str(share.get("expires_at") or "").replace("Z", "+00:00")
                )
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= datetime.now(timezone.utc):
                    return None
            except ValueError:
                return None
            record = self._data.setdefault("decision_records", {}).get(
                str(share.get("decision_record_id") or "")
            )
            if not isinstance(record, dict) or str(record.get("workspace_id") or "") != str(share.get("workspace_id") or ""):
                return None
            return {"record": dict(record), "expires_at": share.get("expires_at")}

    def create_decision_record_approver(
        self,
        *,
        workspace_id: str,
        decision_record_id: str,
        token_hash: str,
        created_by: str,
        email: str,
        expires_at: str,
    ) -> None:
        wid = self._require_workspace(workspace_id)
        record_id = str(decision_record_id or "").strip()
        if not any(
            str(row.get("id") or row.get("decision_id") or "") == record_id
            for row in self.list_decision_records(workspace_id=wid)
        ):
            raise WorkspaceAccessError("Decision record was not found.")
        with _LOCK:
            self._data.setdefault("decision_record_approvers", {})[token_hash] = {
                "workspace_id": wid,
                "decision_record_id": record_id,
                "created_by": str(created_by or ""),
                "email": str(email or "").lower(),
                "status": "pending",
                "response_rationale": None,
                "created_at": _now(),
                "expires_at": expires_at,
                "responded_at": None,
            }
            self.save()

    def get_decision_record_approver(self, token_hash: str) -> dict[str, Any] | None:
        candidate = str(token_hash or "").strip()
        with _LOCK:
            invite = dict(self._data.setdefault("decision_record_approvers", {}).get(candidate) or {})
        if not invite or invite.get("status") == "revoked":
            return None
        try:
            expires = datetime.fromisoformat(str(invite.get("expires_at") or "").replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                return None
        except ValueError:
            return None
        record = next((row for row in self.list_decision_records(workspace_id=str(invite.get("workspace_id") or ""))
                       if str(row.get("id") or row.get("decision_id") or "") == str(invite.get("decision_record_id") or "")), None)
        if not record:
            return None
        return {
            "email": str(invite.get("email") or ""),
            "status": str(invite.get("status") or "pending"),
            "response_rationale": invite.get("response_rationale"),
            "responded_at": invite.get("responded_at"),
            "record": record,
            "expires_at": invite.get("expires_at"),
        }

    def list_decision_record_approvers(
        self, *, workspace_id: str, status: str = "pending"
    ) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        wanted = str(status or "pending").strip().lower()
        now = datetime.now(timezone.utc)
        with _LOCK:
            rows = []
            for invite in self._data.setdefault("decision_record_approvers", {}).values():
                if str(invite.get("workspace_id") or "") != wid:
                    continue
                if str(invite.get("status") or "").lower() != wanted:
                    continue
                try:
                    expires = datetime.fromisoformat(
                        str(invite.get("expires_at") or "").replace("Z", "+00:00")
                    )
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if expires <= now:
                    continue
                rows.append({
                    "decision_record_id": str(invite.get("decision_record_id") or ""),
                    "status": wanted,
                    "expires_at": invite.get("expires_at"),
                })
            return rows

    def respond_to_decision_record_approver(
        self, token_hash: str, *, decision: str, rationale: str
    ) -> bool:
        with _LOCK:
            invite = self._data.setdefault("decision_record_approvers", {}).get(str(token_hash or "").strip())
            if not invite or invite.get("status") != "pending":
                return False
            try:
                expires = datetime.fromisoformat(str(invite.get("expires_at") or "").replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
            except ValueError:
                return False
            if expires <= datetime.now(timezone.utc):
                return False
            invite.update({"status": decision, "response_rationale": rationale, "responded_at": _now()})
            self.save()
            return True

    def revoke_decision_record_approver(self, token_hash: str) -> None:
        with _LOCK:
            invite = self._data.setdefault("decision_record_approvers", {}).get(str(token_hash or "").strip())
            if invite and invite.get("status") == "pending":
                invite["status"] = "revoked"
                self.save()

    def create_procurement_quote(
        self, quote: dict[str, Any], *, workspace_id: str
    ) -> dict[str, Any]:
        """Save a quote snapshot inside a workspace and saved-analysis scope."""
        wid = self._require_workspace(workspace_id)
        analysis_id = str(quote.get("analysis_id") or "").strip()
        if not analysis_id or not self.get_report(analysis_id, workspace_id=wid):
            raise WorkspaceAccessError(f"analysis {analysis_id} was not found")
        with _LOCK:
            saved = dict(quote)
            quote_id = str(saved.get("quote_id") or uuid.uuid4())
            saved.update(
                {
                    "id": quote_id,
                    "quote_id": quote_id,
                    "workspace_id": wid,
                    "created_at": str(saved.get("created_at") or _now()),
                }
            )
            self._data.setdefault("procurement_quotes", {})[quote_id] = saved
            self.save()
            return dict(saved)

    def list_procurement_quotes(
        self,
        *,
        workspace_id: str,
        analysis_id: str,
        requested_mpn: str | None = None,
        requested_manufacturer: str | None = None,
    ) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        aid = str(analysis_id or "").strip()
        mpn = str(requested_mpn or "").strip().casefold()
        maker = str(requested_manufacturer or "").strip().casefold()
        with _LOCK:
            rows = []
            for quote in self._data.setdefault("procurement_quotes", {}).values():
                if quote.get("workspace_id") != wid or str(quote.get("analysis_id") or "") != aid:
                    continue
                if mpn and str(quote.get("requested_mpn") or "").strip().casefold() != mpn:
                    continue
                if maker and str(quote.get("requested_manufacturer") or "").strip().casefold() != maker:
                    continue
                rows.append(dict(quote))
            return sorted(
                rows, key=lambda row: str(row.get("created_at") or ""), reverse=True
            )

    def list_projects(self, *, workspace_id: str) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            projects = []
            for project in self._data["projects"].values():
                if project.get("workspace_id") != wid:
                    continue
                boms = [
                    self._bom_summary(bom)
                    for bom in self._data["boms"].values()
                    if bom.get("project_id") == project["id"]
                    and bom.get("workspace_id") == wid
                ]
                projects.append(
                    {
                        **project,
                        "bom_count": len(boms),
                        "boms": sorted(
                            boms,
                            key=lambda row: str(row.get("updated_at") or ""),
                            reverse=True,
                        ),
                    }
                )
            return sorted(
                projects, key=lambda row: str(row.get("updated_at") or ""), reverse=True
            )

    def _bom_summary(self, bom: dict[str, Any]) -> dict[str, Any]:
        analysis_id = bom.get("latest_analysis_id")
        analysis = self._data["analyses"].get(analysis_id or "", {})
        if analysis and analysis.get("workspace_id") != bom.get("workspace_id"):
            analysis = {}
        return {
            **bom,
            "latest_analysis": analysis or None,
            "health_score": analysis.get("health_score"),
            "high_risk_count": analysis.get("high_risk_count"),
            "has_hierarchy": analysis.get("has_hierarchy"),
            "top_rolled_risk": analysis.get("top_rolled_risk"),
        }

    def home_dashboard(
        self, *, workspace_id: str, production: bool = False
    ) -> dict[str, Any]:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            analyses = customer_visible_analyses(
                self.list_reports(workspace_id=wid), production=production
            )
            projects = customer_visible_projects(
                self.list_projects(workspace_id=wid), analyses, production=production
            )
            bom_count = sum(
                1
                for project in projects
                for bom in project.get("boms") or []
            )
            priority: list[dict[str, Any]] = []
            for analysis in analyses[:8]:
                report = self._data["reports"].get(analysis["id"]) or {}
                if report.get("workspace_id") != wid:
                    continue
                hierarchy = report.get("hierarchy") or {}
                contributors = hierarchy.get("priority_contributors") or []
                if contributors:
                    for item in contributors[:3]:
                        priority.append(
                            {
                                "analysis_id": analysis["id"],
                                "project_name": analysis.get("project_name"),
                                "bom_name": analysis.get("bom_name"),
                                "mpn": item.get("mpn"),
                                "risk_level": item.get("risk_level"),
                                "bom_path": item.get("bom_path"),
                                "why": item.get("why"),
                                "evidence_source": item.get("evidence_source"),
                                "action": "Review drill-down evidence in report",
                            }
                        )
                elif int(analysis.get("high_risk_count") or 0) > 0:
                    priority.append(
                        {
                            "analysis_id": analysis["id"],
                            "project_name": analysis.get("project_name"),
                            "bom_name": analysis.get("bom_name"),
                            "mpn": None,
                            "risk_level": "High",
                            "bom_path": None,
                            "why": f"{analysis.get('high_risk_count')} high-risk parts in latest analysis",
                            "evidence_source": "synthetic-preview-analysis",
                            "action": "Open report and review high-risk rows",
                        }
                    )
            next_actions = [
                {
                    "title": "Reopen an active project BOM",
                    "detail": "Workspace-scoped saved analyses in the local preview store.",
                    "href": "/reports",
                    "live": True,
                },
                {
                    "title": "Review rolled-up assembly risk",
                    "detail": "Nested BOMs show assembly risk with part-level drill-down.",
                    "href": analyses[0]["id"] if analyses else "/bom-analyzer",
                    "href_kind": "report" if analyses else "route",
                    "live": True,
                },
                {
                    "title": "Automated lifecycle/stock monitoring + email",
                    "detail": "Partial — durable alerts/preferences exist; scheduled refresh and real alert email remain disabled.",
                    "href": "/monitoring",
                    "live": False,
                },
                {
                    "title": "Plan limits on active BOMs / tracked parts",
                    "detail": "Partial — server plan limits and /plan/usage metering are enforced; Stripe checkout remains disabled.",
                    "href": "/settings",
                    "live": False,
                },
            ]
            return {
                "ok": True,
                "mode": "synthetic-preview" if not production else "workspace-home",
                "workspace_id": wid,
                "persistence": "migration-workspace-store",
                "gap": (
                    "This local preview uses temporary file storage and does not survive service restarts. "
                    "Deployed workspaces use durable storage."
                ),
                "metrics": {
                    "active_projects": len(projects),
                    "saved_boms": bom_count,
                    "saved_analyses": len(analyses),
                    "priority_items": len(priority),
                },
                "projects": projects[:12],
                "recent_analyses": analyses[:12],
                "priority_risks": priority[:12],
                "next_actions": next_actions,
            }

    def analyses_and_parts(
        self, *, workspace_id: str, analysis_id: str | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            if analysis_id:
                report = self._data["reports"].get(analysis_id)
                if not report:
                    return [], []
                if report.get("workspace_id") != wid:
                    raise WorkspaceAccessError(
                        f"analysis {analysis_id} is not in workspace {wid}"
                    )
                selected_ids = [analysis_id]
            else:
                selected_ids = [
                    rid
                    for rid, report in self._data["reports"].items()
                    if report.get("workspace_id") == wid
                ]
            analyses: list[dict[str, Any]] = []
            parts: list[dict[str, Any]] = []
            for aid in selected_ids:
                report = self._data["reports"].get(aid or "")
                analysis = self._data["analyses"].get(aid or "")
                if not report or report.get("workspace_id") != wid:
                    continue
                analyses.append(
                    analysis
                    or {
                        "id": report["id"],
                        "workspace_id": wid,
                        "filename": report.get("filename"),
                        "project_name": report.get("project_name"),
                        "created_at": report.get("created_at"),
                        "health_score": report.get("health_score"),
                        "high_risk_count": report.get("high_risk_count"),
                        "total_parts": report.get("total_parts"),
                        "mode": report.get("mode"),
                    }
                )
                for part in report.get("parts") or []:
                    enriched = dict(part)
                    enriched["analysis_id"] = report["id"]
                    enriched["workspace_id"] = wid
                    enriched.setdefault("filename", report.get("filename") or "bom.csv")
                    parts.append(enriched)
            return analyses, parts

    def update_project(
        self, project_id: str, *, workspace_id: str, name: str
    ) -> dict[str, Any]:
        wid = self._require_workspace(workspace_id)
        new_name = str(name or "").strip()
        if not new_name:
            raise ValueError("name is required")
        with _LOCK:
            project = self._data["projects"].get(project_id)
            if not project:
                raise LookupError(f"project {project_id} not found")
            if project.get("workspace_id") != wid:
                raise WorkspaceAccessError(
                    f"project {project_id} is not in workspace {wid}"
                )
            if any(
                other_id != project_id
                and other.get("workspace_id") == wid
                and str(other.get("name") or "").casefold() == new_name.casefold()
                for other_id, other in self._data["projects"].items()
            ):
                raise ValueError("A project with this name already exists.")
            project["name"] = new_name
            project["updated_at"] = _now()
            for analysis_id, analysis in self._data["analyses"].items():
                if analysis.get("project_id") != project_id or analysis.get("workspace_id") != wid:
                    continue
                bom_name = str(analysis.get("bom_name") or "Saved BOM")
                title = analysis_title_for_upload(new_name, bom_name)
                analysis["project_name"] = title
                analysis["updated_at"] = _now()
                report = self._data["reports"].get(analysis_id)
                if report and report.get("workspace_id") == wid:
                    report["project_name"] = title
            self.save()
            return dict(project)

    def update_bom(
        self,
        bom_id: str,
        *,
        workspace_id: str,
        name: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            bom = self._data["boms"].get(bom_id)
            if not bom:
                raise LookupError(f"BOM {bom_id} not found")
            if bom.get("workspace_id") != wid:
                raise WorkspaceAccessError(f"BOM {bom_id} is not in workspace {wid}")
            new_name = str(name if name is not None else bom.get("name") or "").strip()
            if not new_name:
                raise ValueError("name is required")
            current_project_id = str(bom.get("project_id") or "")
            target_project_id = str(project_id or current_project_id).strip()
            target_project = self._data["projects"].get(target_project_id)
            if not target_project or target_project.get("workspace_id") != wid:
                raise LookupError(f"project {target_project_id} not found")
            if any(
                other_id != bom_id
                and other.get("workspace_id") == wid
                and other.get("project_id") == target_project_id
                and str(other.get("name") or "").casefold() == new_name.casefold()
                for other_id, other in self._data["boms"].items()
            ):
                raise ValueError("A BOM with this name already exists in this project.")
            project_name = str(target_project.get("name") or DEFAULT_WORKSPACE_PROJECT)
            bom["name"] = new_name
            bom["project_id"] = target_project_id
            bom["updated_at"] = _now()
            for analysis_id, analysis in self._data["analyses"].items():
                if analysis.get("bom_id") != bom_id or analysis.get("workspace_id") != wid:
                    continue
                title = analysis_title_for_upload(project_name, new_name)
                analysis["project_id"] = target_project_id
                analysis["bom_name"] = new_name
                analysis["project_name"] = title
                analysis["updated_at"] = _now()
                report = self._data["reports"].get(analysis_id)
                if report and report.get("workspace_id") == wid:
                    report["project_id"] = target_project_id
                    report["bom_name"] = new_name
                    report["project_name"] = title
            for affected_project_id in {current_project_id, target_project_id}:
                project = self._data["projects"].get(affected_project_id)
                if project and project.get("workspace_id") == wid:
                    project["updated_at"] = _now()
            self.save()
            return dict(bom)

    def delete_bom(self, bom_id: str, *, workspace_id: str) -> list[str] | None:
        """Delete one BOM and all of its saved revisions, reports, and records.

        Return the deleted analysis IDs so the API can clear monitoring history.
        None means the BOM does not exist; workspace mismatches raise.
        """
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            bom = self._data["boms"].get(bom_id)
            if not bom:
                return None
            if bom.get("workspace_id") != wid:
                raise WorkspaceAccessError(f"BOM {bom_id} is not in workspace {wid}")
            analysis_ids = [
                aid
                for aid, row in self._data["analyses"].items()
                if row.get("bom_id") == bom_id and row.get("workspace_id") == wid
            ]
            analysis_id_set = set(analysis_ids)
            for aid in analysis_ids:
                self._data["analyses"].pop(aid, None)
                self._data["reports"].pop(aid, None)
            self._data["decision_records"] = {
                decision_id: row
                for decision_id, row in self._data.get("decision_records", {}).items()
                if not (
                    row.get("workspace_id") == wid
                    and str(row.get("analysis_id") or "") in analysis_id_set
                )
            }
            self._data["procurement_quotes"] = {
                quote_id: row
                for quote_id, row in self._data.get("procurement_quotes", {}).items()
                if not (
                    row.get("workspace_id") == wid
                    and str(row.get("analysis_id") or "") in analysis_id_set
                )
            }
            self._data["revisions"] = {
                revision_id: row
                for revision_id, row in self._data["revisions"].items()
                if row.get("bom_id") != bom_id or row.get("workspace_id") != wid
            }
            self._data["boms"].pop(bom_id, None)
            project = self._data["projects"].get(str(bom.get("project_id") or ""))
            if project and project.get("workspace_id") == wid:
                project["updated_at"] = _now()
            self.save()
            return analysis_ids

    def delete_analysis(self, analysis_id: str, *, workspace_id: str) -> bool:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            report = self._data["reports"].get(analysis_id)
            analysis = self._data["analyses"].get(analysis_id)
            if not report and not analysis:
                return False
            owner = (report or analysis or {}).get("workspace_id")
            if owner != wid:
                raise WorkspaceAccessError(
                    f"analysis {analysis_id} is not in workspace {wid}"
                )
            self._data["reports"].pop(analysis_id, None)
            self._data["analyses"].pop(analysis_id, None)
            self._data["decision_records"] = {
                decision_id: row
                for decision_id, row in self._data.get("decision_records", {}).items()
                if not (
                    row.get("workspace_id") == wid
                    and str(row.get("analysis_id") or "") == analysis_id
                )
            }
            for quote_id, quote in list(self._data.setdefault("procurement_quotes", {}).items()):
                if quote.get("analysis_id") == analysis_id and quote.get("workspace_id") == wid:
                    self._data["procurement_quotes"].pop(quote_id, None)
            for bom in self._data["boms"].values():
                if bom.get("latest_analysis_id") == analysis_id and bom.get(
                    "workspace_id"
                ) == wid:
                    bom["latest_analysis_id"] = None
            for rev in self._data["revisions"].values():
                if rev.get("latest_analysis_id") == analysis_id and rev.get(
                    "workspace_id"
                ) == wid:
                    rev["latest_analysis_id"] = None
            self.save()
            return True

    def delete_project(self, project_id: str, *, workspace_id: str) -> bool:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            project = self._data["projects"].get(project_id)
            if not project:
                return False
            if project.get("workspace_id") != wid:
                raise WorkspaceAccessError(
                    f"project {project_id} is not in workspace {wid}"
                )
            bom_ids = [
                bid
                for bid, bom in self._data["boms"].items()
                if bom.get("project_id") == project_id and bom.get("workspace_id") == wid
            ]
            rev_ids = [
                rid
                for rid, rev in self._data["revisions"].items()
                if rev.get("bom_id") in bom_ids and rev.get("workspace_id") == wid
            ]
            analysis_ids = [
                aid
                for aid, row in self._data["analyses"].items()
                if row.get("project_id") == project_id and row.get("workspace_id") == wid
            ]
            for aid in analysis_ids:
                self._data["analyses"].pop(aid, None)
                self._data["reports"].pop(aid, None)
            for quote_id, quote in list(self._data.setdefault("procurement_quotes", {}).items()):
                if quote.get("analysis_id") in analysis_ids and quote.get("workspace_id") == wid:
                    self._data["procurement_quotes"].pop(quote_id, None)
            for rid in rev_ids:
                self._data["revisions"].pop(rid, None)
            for bid in bom_ids:
                self._data["boms"].pop(bid, None)
            self._data["projects"].pop(project_id, None)
            self.save()
            return True


_STORE: Any | None = None


def describe_persistence() -> dict[str, Any]:
    """Health/diagnostic snapshot — never treats production SUPABASE_* as migration DB."""
    db_url = migration_database_url()
    railway_env = (os.environ.get("RAILWAY_ENVIRONMENT") or "").strip()
    if db_url:
        return {
            "backend": "postgres",
            "durable_across_redeploy": True,
            "database_configured": True,
            "ephemeral_file_allowed": False,
            "label": "Saved BOM and project records are stored in your workspace database.",
            "service_gaps": [
                "Monitoring email is not connected yet.",
                "Billing checkout is not connected yet.",
                "Design-tool connectors are not connected yet.",
            ],
            "railway_environment": railway_env or None,
        }
    if allow_ephemeral_file_store():
        return {
            "backend": "local-file-preview",
            "durable_across_redeploy": False,
            "database_configured": False,
            "ephemeral_file_allowed": True,
            "label": "Local preview storage is temporary and does not survive service restarts.",
            "railway_environment": railway_env or None,
        }
    return {
        "backend": "unconfigured",
        "durable_across_redeploy": False,
        "database_configured": False,
        "ephemeral_file_allowed": False,
        "label": (
            "Workspace database storage is not configured for this deployment; "
            "temporary local storage is disabled."
        ),
        "railway_environment": railway_env or None,
    }


def get_store(path: Path | None = None) -> Any:
    """Return Postgres store when configured; else ephemeral file if allowed."""
    global _STORE
    if path is not None:
        return WorkspaceStore(path)

    db_url = migration_database_url()
    if db_url:
        if _STORE is not None and getattr(_STORE, "backend", None) == "postgres":
            return _STORE
        from apps.api.postgres_store import PostgresWorkspaceStore

        _STORE = PostgresWorkspaceStore(db_url)
        return _STORE

    if not allow_ephemeral_file_store():
        raise PersistenceNotConfiguredError(
            "Workspace database storage is not configured for this deployment. "
            "Temporary file storage is disabled "
            "on Railway unless CADIVOR_ALLOW_EPHEMERAL_FILE_STORE=1."
        )

    if _STORE is None or getattr(_STORE, "backend", None) != "file":
        _STORE = WorkspaceStore()
    return _STORE


def reset_store_for_tests(path: Path) -> WorkspaceStore:
    global _STORE
    os.environ["CADIVOR_ALLOW_EPHEMERAL_FILE_STORE"] = "1"
    os.environ.pop("CADIVOR_MIGRATION_DATABASE_URL", None)
    _STORE = WorkspaceStore(path)
    _STORE.clear()
    return _STORE
