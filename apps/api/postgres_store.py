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

from apps.api.json_safe import json_safe
from apps.api.workspace_store import WorkspaceAccessError
from apps.api.report_visibility import customer_visible_analyses, customer_visible_projects

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
                    "TRUNCATE migration_procurement_quotes, migration_decision_records, migration_reports, migration_analyses, "
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
                safe_report = json_safe(report)
                assert isinstance(safe_report, dict)
                report = safe_report
                report_payload = json.dumps(report, allow_nan=False)
                report_write = conn.execute(
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
                        report_payload,
                        analysis["created_at"],
                        now,
                    ),
                )
                # ON CONFLICT with a mismatched workspace updates 0 rows and
                # would otherwise return persisted=True without storing payload.
                if getattr(report_write, "rowcount", None) == 0:
                    raise WorkspaceAccessError(
                        f"analysis {analysis_id} could not be saved for workspace {wid}"
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

    def update_analysis_health(
        self,
        analysis_id: str,
        *,
        workspace_id: str,
        health: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Persist recalculated health metadata for an existing workspace report."""
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT workspace_id, payload FROM migration_reports WHERE id = %s",
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
            updated_report = dict(payload)
            updated_report.update(health)
            safe_report = json_safe(updated_report)
            conn.execute(
                "UPDATE migration_reports SET payload = %s::jsonb, updated_at = NOW() WHERE id = %s AND workspace_id = %s",
                (json.dumps(safe_report, allow_nan=False), analysis_id, wid),
            )
            conn.execute(
                "UPDATE migration_analyses SET health_score = %s, health_status = %s WHERE id = %s AND workspace_id = %s",
                (
                    health.get("health_score"),
                    health.get("health_status"),
                    analysis_id,
                    wid,
                ),
            )
            conn.commit()
            return dict(safe_report)

    def list_reports(self, *, workspace_id: str) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT a.id, a.workspace_id, a.project_id, a.bom_id, a.revision_id,
                       a.project_name, a.bom_name, a.revision, a.filename, a.created_at,
                       a.updated_at, a.health_score, a.health_status, a.high_risk_count,
                       a.medium_risk_count, a.low_risk_count, a.total_parts, a.mode,
                       a.has_hierarchy, a.top_rolled_risk, p.name AS project_label,
                       r.payload->>'summary_message' AS summary_message,
                       r.payload->>'needs_verification_count' AS needs_verification_count
                FROM migration_analyses AS a
                LEFT JOIN migration_projects AS p
                  ON p.id = a.project_id AND p.workspace_id = a.workspace_id
                LEFT JOIN migration_reports AS r
                  ON r.id = a.id AND r.workspace_id = a.workspace_id
                WHERE a.workspace_id = %s
                ORDER BY a.created_at DESC
                """,
                (wid,),
            ).fetchall()
            out = []
            for row in rows:
                item = dict(row)
                item["id"] = str(item["id"])
                item["analysis_id"] = item["id"]
                for key in ("created_a