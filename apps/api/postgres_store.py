"""Postgres-backed workspace store for the Next.js migration app.

Requires CADIVOR_MIGRATION_DATABASE_URL pointing at a dedicated database,
separate from the existing Streamlit app's saved-BOM data.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.saved_bom_project import (
    DEFAULT_WORKSPACE_PROJECT,
    analysis_title_for_upload,
)

from apps.api.workspace_store import WorkspaceAccessError

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "sandbox_workspace.sql"
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "psycopg is required for CADIVOR_MIGRATION_DATABASE_URL. "
            "Install apps/api/requirements.txt extras."
        ) from exc
    return psycopg, dict_row


class PostgresWorkspaceStore:
    """Tenant-scoped durable store. Same surface as file WorkspaceStore."""

    backend = "postgres"
    durable_across_redeploy = True

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = (
            database_url
            or os.environ.get("CADIVOR_MIGRATION_DATABASE_URL")
            or ""
        ).strip()
        if not self.database_url:
            raise ValueError("CADIVOR_MIGRATION_DATABASE_URL is required")
        # Compatibility with health() which inspects .path on file store
        self.path = Path("postgres://migration-postgres")
        self._schema_ready = False
        self.ensure_schema()

    def _connect(self):
        psycopg, dict_row = _require_psycopg()
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with _LOCK:
            if self._schema_ready:
                return
            sql = _SCHEMA_PATH.read_text(encoding="utf-8")
            with self._connect() as conn:
                conn.execute(sql)
                conn.commit()
            self._schema_ready = True

    def clear(self) -> None:
        """Test helper — wipe all migration tables."""
        with _LOCK:
            with self._connect() as conn:
                conn.execute(
                    "TRUNCATE migration_decision_records, migration_reports, migration_analyses, "
                    "migration_revisions, migration_boms, migration_projects "
                    "CASCADE"
                )
                conn.commit()

    def _require_workspace(self, workspace_id: str) -> str:
        wid = str(workspace_id or "").strip()
        if not wid:
            raise ValueError("workspace_id is required")
        return wid

    def upsert_analysis_report(
        self,
        report: dict[str, Any],
        *,
        workspace_id: str,
        project_name: str | None = None,
        bom_name: str | None = None,
        revision: str | None = None,
    ) -> dict[str, Any]:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            filename = str(report.get("filename") or "bom.csv")
            project = (project_name or "").strip() or DEFAULT_WORKSPACE_PROJECT
            bom = (bom_name or "").strip() or filename
            rev = (revision or "").strip() or "A"
            title = analysis_title_for_upload(project, bom)

            with self._connect() as conn:
                project_id = self._ensure_project(conn, project, wid)
                bom_id = self._ensure_bom(conn, project_id, bom, filename, wid)
                revision_id = self._ensure_revision(conn, bom_id, rev, wid)

                analysis_id = str(report.get("id") or uuid.uuid4())
                report = dict(report)
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
                report["persistence"] = "migration-postgres-store"

                now = _now()
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
                    "created_at": report.get("created_at") or now,
                    "updated_at": now,
                    "health_score": report.get("health_score"),
                    "health_status": report.get("health_status"),
                    "high_risk_count": report.get("high_risk_count"),
                    "medium_risk_count": report.get("medium_risk_count"),
                    "low_risk_count": report.get("low_risk_count"),
                    "total_parts": report.get("total_parts"),
                    "mode": report.get("mode"),
                    "has_hierarchy": bool(
                        (report.get("hierarchy") or {}).get("has_hierarchy")
                    ),
                    "top_rolled_risk": (
                        (report.get("hierarchy") or {}).get("top_level") or {}
                    ).get("rolled_risk_level"),
                }

                conn.execute(
                    """
                    INSERT INTO migration_analyses (
                      id, workspace_id, project_id, bom_id, revision_id,
                      project_name, bom_name, revision, filename,
                      created_at, updated_at, health_score, health_status,
                      high_risk_count, medium_risk_count, low_risk_count,
                      total_parts, mode, has_hierarchy, top_rolled_risk
                    ) VALUES (
                      %(id)s, %(workspace_id)s, %(project_id)s, %(bom_id)s,
                      %(revision_id)s, %(project_name)s, %(bom_name)s,
                      %(revision)s, %(filename)s, %(created_at)s, %(updated_at)s,
                      %(health_score)s, %(health_status)s, %(high_risk_count)s,
                      %(medium_risk_count)s, %(low_risk_count)s, %(total_parts)s,
                      %(mode)s, %(has_hierarchy)s, %(top_rolled_risk)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                      project_name = EXCLUDED.project_name,
                      bom_name = EXCLUDED.bom_name,
                      revision = EXCLUDED.revision,
                      filename = EXCLUDED.filename,
                      updated_at = EXCLUDED.updated_at,
                      health_score = EXCLUDED.health_score,
                      health_status = EXCLUDED.health_status,
                      high_risk_count = EXCLUDED.high_risk_count,
                      medium_risk_count = EXCLUDED.medium_risk_count,
                      low_risk_count = EXCLUDED.low_risk_count,
                      total_parts = EXCLUDED.total_parts,
                      mode = EXCLUDED.mode,
                      has_hierarchy = EXCLUDED.has_hierarchy,
                      top_rolled_risk = EXCLUDED.top_rolled_risk
                    WHERE migration_analyses.workspace_id = EXCLUDED.workspace_id
                    """,
                    analysis,
                )
                conn.execute(
                    """
                    INSERT INTO migration_reports (id, workspace_id, payload, created_at, updated_at)
                    VALUES (%s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      payload = EXCLUDED.payload,
                      updated_at = EXCLUDED.updated_at
                    WHERE migration_reports.workspace_id = EXCLUDED.workspace_id
                    """,
                    (
                        analysis_id,
                        wid,
                        json.dumps(report),
                        analysis["created_at"],
                        now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE migration_revisions
                    SET latest_analysis_id = %s, updated_at = %s
                    WHERE id = %s AND workspace_id = %s
                    """,
                    (analysis_id, now, revision_id, wid),
                )
                conn.execute(
                    """
                    UPDATE migration_boms
                    SET latest_analysis_id = %s, updated_at = %s
                    WHERE id = %s AND workspace_id = %s
                    """,
                    (analysis_id, now, bom_id, wid),
                )
                conn.execute(
                    """
                    UPDATE migration_projects
                    SET updated_at = %s
                    WHERE id = %s AND workspace_id = %s
                    """,
                    (now, project_id, wid),
                )
                conn.commit()
                return report

    def _ensure_project(self, conn, name: str, workspace_id: str) -> str:
        row = conn.execute(
            """
            SELECT id FROM migration_projects
            WHERE workspace_id = %s AND name = %s
            """,
            (workspace_id, name),
        ).fetchone()
        if row:
            return str(row["id"])
        pid = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """
            INSERT INTO migration_projects (id, workspace_id, name, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (pid, workspace_id, name, now, now),
        )
        return pid

    def _ensure_bom(
        self, conn, project_id: str, name: str, filename: str, workspace_id: str
    ) -> str:
        row = conn.execute(
            """
            SELECT id FROM migration_boms
            WHERE workspace_id = %s AND project_id = %s AND name = %s
            """,
            (workspace_id, project_id, name),
        ).fetchone()
        if row:
            return str(row["id"])
        bid = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """
            INSERT INTO migration_boms (
              id, project_id, workspace_id, name, filename, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (bid, project_id, workspace_id, name, filename, now, now),
        )
        return bid

    def _ensure_revision(self, conn, bom_id: str, revision: str, workspace_id: str) -> str:
        row = conn.execute(
            """
            SELECT id FROM migration_revisions
            WHERE workspace_id = %s AND bom_id = %s AND revision = %s
            """,
            (workspace_id, bom_id, revision),
        ).fetchone()
        if row:
            return str(row["id"])
        rid = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """
            INSERT INTO migration_revisions (
              id, bom_id, workspace_id, revision, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (rid, bom_id, workspace_id, revision, now, now),
        )
        return rid

    def get_report(
        self, analysis_id: str, *, workspace_id: str
    ) -> dict[str, Any] | None:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT workspace_id, payload FROM migration_reports WHERE id = %s
                """,
                (analysis_id,),
            ).fetchone()
            if not row:
                return None
            if row["workspace_id"] != wid:
                raise WorkspaceAccessError(
                    f"analysis {analysis_id} is not in workspace {wid}"
                )
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            return dict(payload)

    def list_reports(self, *, workspace_id: str) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, workspace_id, project_id, bom_id, revision_id,
                       project_name, bom_name, revision, filename, created_at,
                       updated_at, health_score, health_status, high_risk_count,
                       medium_risk_count, low_risk_count, total_parts, mode,
                       has_hierarchy, top_rolled_risk
                FROM migration_analyses
                WHERE workspace_id = %s
                ORDER BY created_at DESC
                """,
                (wid,),
            ).fetchall()
            out = []
            for row in rows:
                item = dict(row)
                item["id"] = str(item["id"])
                item["analysis_id"] = item["id"]
                for key in ("created_at", "updated_at"):
                    if item.get(key) is not None:
                        item[key] = item[key].isoformat()
                out.append(item)
            return out

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
            created_at = str(saved.get("created_at") or _now())
            saved.update(
                {
                    "id": decision_id,
                    "decision_id": decision_id,
                    "workspace_id": wid,
                    "created_at": created_at,
                }
            )
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO migration_decision_records
                      (id, workspace_id, analysis_id, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        decision_id,
                        wid,
                        analysis_id or None,
                        created_at,
                        json.dumps(saved),
                    ),
                )
                conn.commit()
            return saved

    def list_decision_records(
        self, *, workspace_id: str, analysis_id: str | None = None
    ) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        aid = str(analysis_id or "").strip()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM migration_decision_records
                WHERE workspace_id = %s
                  AND (%s = '' OR analysis_id = %s)
                ORDER BY created_at DESC
                """,
                (wid, aid, aid),
            ).fetchall()
        records = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, dict):
                records.append(dict(payload))
        return records

    def list_projects(self, *, workspace_id: str) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            projects = conn.execute(
                """
                SELECT * FROM migration_projects
                WHERE workspace_id = %s
                ORDER BY updated_at DESC
                """,
                (wid,),
            ).fetchall()
            out = []
            for project in projects:
                boms = conn.execute(
                    """
                    SELECT * FROM migration_boms
                    WHERE workspace_id = %s AND project_id = %s
                    ORDER BY updated_at DESC
                    """,
                    (wid, project["id"]),
                ).fetchall()
                summaries = [self._bom_summary(conn, dict(bom)) for bom in boms]
                item = dict(project)
                item["id"] = str(item["id"])
                for key in ("created_at", "updated_at"):
                    if item.get(key) is not None:
                        item[key] = item[key].isoformat()
                item["bom_count"] = len(summaries)
                item["boms"] = summaries
                out.append(item)
            return out

    def _bom_summary(self, conn, bom: dict[str, Any]) -> dict[str, Any]:
        analysis_id = bom.get("latest_analysis_id")
        analysis = None
        if analysis_id:
            row = conn.execute(
                """
                SELECT * FROM migration_analyses
                WHERE id = %s AND workspace_id = %s
                """,
                (analysis_id, bom.get("workspace_id")),
            ).fetchone()
            if row:
                analysis = dict(row)
                analysis["id"] = str(analysis["id"])
                for key in ("created_at", "updated_at"):
                    if analysis.get(key) is not None:
                        analysis[key] = analysis[key].isoformat()
        item = dict(bom)
        item["id"] = str(item["id"])
        for key in ("created_at", "updated_at"):
            if item.get(key) is not None:
                item[key] = item[key].isoformat()
        return {
            **item,
            "latest_analysis": analysis,
            "health_score": (analysis or {}).get("health_score"),
            "high_risk_count": (analysis or {}).get("high_risk_count"),
            "has_hierarchy": (analysis or {}).get("has_hierarchy"),
            "top_rolled_risk": (analysis or {}).get("top_rolled_risk"),
        }

    def home_dashboard(self, *, workspace_id: str) -> dict[str, Any]:
        wid = self._require_workspace(workspace_id)
        projects = self.list_projects(workspace_id=wid)
        analyses = self.list_reports(workspace_id=wid)
        with self._connect() as conn:
            bom_count = conn.execute(
                "SELECT COUNT(*) AS c FROM migration_boms WHERE workspace_id = %s",
                (wid,),
            ).fetchone()["c"]
        priority: list[dict[str, Any]] = []
        for analysis in analyses[:8]:
            report = self.get_report(analysis["id"], workspace_id=wid) or {}
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
                "detail": "Open saved analyses from this workspace.",
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
                "title": "Plan access and upgrades",
                "detail": "Review current access and available plan upgrades in Workspace Settings.",
                "href": "/settings",
                "live": True,
            },
        ]
        return {
            "ok": True,
            "mode": "synthetic-preview",
            "workspace_id": wid,
            "persistence": "migration-postgres-store",
            "metrics": {
                "active_projects": len(projects),
                "saved_boms": int(bom_count),
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
        if analysis_id:
            report = self.get_report(analysis_id, workspace_id=wid)
            if not report:
                return [], []
            selected_ids = [analysis_id]
        else:
            selected_ids = [row["id"] for row in self.list_reports(workspace_id=wid)]
        analyses: list[dict[str, Any]] = []
        parts: list[dict[str, Any]] = []
        summaries = {row["id"]: row for row in self.list_reports(workspace_id=wid)}
        for aid in selected_ids:
            report = self.get_report(aid, workspace_id=wid)
            if not report:
                continue
            analyses.append(
                summaries.get(aid)
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
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM migration_projects WHERE id = %s",
                    (project_id,),
                ).fetchone()
                if not row:
                    raise LookupError(f"project {project_id} not found")
                if row["workspace_id"] != wid:
                    raise WorkspaceAccessError(
                        f"project {project_id} is not in workspace {wid}"
                    )
                now = _now()
                conn.execute(
                    """
                    UPDATE migration_projects
                    SET name = %s, updated_at = %s
                    WHERE id = %s AND workspace_id = %s
                    """,
                    (new_name, now, project_id, wid),
                )
                conn.commit()
                updated = dict(row)
                updated["name"] = new_name
                updated["updated_at"] = now
                updated["id"] = str(updated["id"])
                if hasattr(updated.get("created_at"), "isoformat"):
                    updated["created_at"] = updated["created_at"].isoformat()
                return updated

    def delete_analysis(self, analysis_id: str, *, workspace_id: str) -> bool:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT workspace_id FROM migration_analyses WHERE id = %s",
                    (analysis_id,),
                ).fetchone()
                if not row:
                    return False
                if row["workspace_id"] != wid:
                    raise WorkspaceAccessError(
                        f"analysis {analysis_id} is not in workspace {wid}"
                    )
                conn.execute(
                    "DELETE FROM migration_reports WHERE id = %s AND workspace_id = %s",
                    (analysis_id, wid),
                )
                conn.execute(
                    "DELETE FROM migration_analyses WHERE id = %s AND workspace_id = %s",
                    (analysis_id, wid),
                )
                conn.execute(
                    """
                    UPDATE migration_boms
                    SET latest_analysis_id = NULL
                    WHERE latest_analysis_id = %s AND workspace_id = %s
                    """,
                    (analysis_id, wid),
                )
                conn.execute(
                    """
                    UPDATE migration_revisions
                    SET latest_analysis_id = NULL
                    WHERE latest_analysis_id = %s AND workspace_id = %s
                    """,
                    (analysis_id, wid),
                )
                conn.commit()
                return True

    def delete_project(self, project_id: str, *, workspace_id: str) -> bool:
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT workspace_id FROM migration_projects WHERE id = %s",
                    (project_id,),
                ).fetchone()
                if not row:
                    return False
                if row["workspace_id"] != wid:
                    raise WorkspaceAccessError(
                        f"project {project_id} is not in workspace {wid}"
                    )
                # Cascade via FKs after deleting reports for analyses under project
                analysis_ids = [
                    str(r["id"])
                    for r in conn.execute(
                        """
                        SELECT id FROM migration_analyses
                        WHERE project_id = %s AND workspace_id = %s
                        """,
                        (project_id, wid),
                    ).fetchall()
                ]
                if analysis_ids:
                    conn.execute(
                        "DELETE FROM migration_reports WHERE id = ANY(%s) AND workspace_id = %s",
                        (analysis_ids, wid),
                    )
                conn.execute(
                    "DELETE FROM migration_projects WHERE id = %s AND workspace_id = %s",
                    (project_id, wid),
                )
                conn.commit()
                return True
