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
                    "TRUNCATE migration_cost_decisions, migration_supply_scenarios, migration_procurement_quotes, migration_decision_records, migration_reports, migration_analyses, "
                    "migration_revisions, migration_boms, migration_projects, migration_ai_credit_usage "
                    "CASCADE"
                )
                conn.commit()

    def get_ai_credit_usage(self, *, user_id: str, usage_month: str) -> int:
        """Return persisted AI credits consumed by one user in a calendar month."""
        uid = str(user_id or "").strip()
        month = str(usage_month or "").strip()
        if not uid or not month:
            return 0
        with self._connect() as conn:
            row = conn.execute(
                "SELECT used_credits FROM migration_ai_credit_usage WHERE user_id = %s AND usage_month = %s",
                (uid, month),
            ).fetchone()
            return max(0, int(row["used_credits"] or 0)) if row else 0

    def reserve_ai_credits(
        self, *, user_id: str, usage_month: str, allowance: int, cost: int = 1
    ) -> int | None:
        """Atomically reserve plan credits; concurrent requests cannot exceed allowance."""
        uid = str(user_id or "").strip()
        month = str(usage_month or "").strip()
        limit = max(0, int(allowance))
        quantity = max(1, int(cost))
        if not uid or not month:
            return None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_ai_credit_usage (user_id, usage_month)
                VALUES (%s, %s)
                ON CONFLICT (user_id, usage_month) DO NOTHING
                """,
                (uid, month),
            )
            row = conn.execute(
                """
                UPDATE migration_ai_credit_usage
                SET used_credits = used_credits + %s, updated_at = NOW()
                WHERE user_id = %s AND usage_month = %s
                  AND used_credits + %s <= %s
                RETURNING used_credits
                """,
                (quantity, uid, month, quantity, limit),
            ).fetchone()
            conn.commit()
            return int(row["used_credits"]) if row else None

    def release_ai_credits(
        self, *, user_id: str, usage_month: str, cost: int = 1
    ) -> int:
        """Refund reserved credits after an unsuccessful provider request."""
        uid = str(user_id or "").strip()
        month = str(usage_month or "").strip()
        quantity = max(1, int(cost))
        if not uid or not month:
            return 0
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE migration_ai_credit_usage
                SET used_credits = GREATEST(0, used_credits - %s), updated_at = NOW()
                WHERE user_id = %s AND usage_month = %s
                RETURNING used_credits
                """,
                (quantity, uid, month),
            ).fetchone()
            conn.commit()
            return max(0, int(row["used_credits"] or 0)) if row else 0

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
                for key in ("created_at", "updated_at"):
                    if item.get(key) is not None:
                        item[key] = item[key].isoformat()
                out.append(item)
            return out

    def list_monitoring_analyses(self) -> list[dict[str, Any]]:
        """Return saved analysis scopes for the scheduler, without report contents."""
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT workspace_id, id AS analysis_id, total_parts FROM migration_analyses "
                "WHERE total_parts > 0 ORDER BY workspace_id, created_at"
            ).fetchall()
        return [
            {
                "workspace_id": str(row["workspace_id"]),
                "analysis_id": str(row["analysis_id"]),
                "total_parts": int(row.get("total_parts") or 0),
            }
            for row in rows
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
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM migration_decision_records WHERE workspace_id = %s AND id = %s",
                (wid, str(decision_record_id or "").strip()),
            ).fetchone()
            if not exists:
                raise WorkspaceAccessError(
                    f"decision {str(decision_record_id or '').strip()} was not found"
                )
            conn.execute(
                """
                INSERT INTO migration_decision_record_shares
                  (token_hash, workspace_id, decision_record_id, created_by, expires_at)
                VALUES (%s, %s, %s, %s, %s::timestamptz)
                """,
                (token_hash, wid, decision_record_id, created_by, expires_at),
            )
            conn.commit()

    def get_decision_record_share(self, token_hash: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT decision.payload, share.expires_at
                  FROM migration_decision_record_shares AS share
                  JOIN migration_decision_records AS decision
                    ON decision.id = share.decision_record_id
                   AND decision.workspace_id = share.workspace_id
                 WHERE share.token_hash = %s
                   AND share.revoked_at IS NULL
                   AND share.expires_at > NOW()
                """,
                (str(token_hash or "").strip(),),
            ).fetchone()
        if not row:
            return None
        record = row["payload"]
        if isinstance(record, str):
            record = json.loads(record)
        expires = row["expires_at"]
        return {
            "record": dict(record) if isinstance(record, dict) else {},
            "expires_at": expires.isoformat() if hasattr(expires, "isoformat") else expires,
        }

    def create_cost_decision(
        self, decision: dict[str, Any], *, workspace_id: str
    ) -> dict[str, Any]:
        """Persist a cost/sourcing decision snapshot against its saved BOM."""
        wid = self._require_workspace(workspace_id)
        analysis_id = str(decision.get("analysis_id") or "").strip()
        if not analysis_id or not self.get_report(analysis_id, workspace_id=wid):
            raise WorkspaceAccessError(f"analysis {analysis_id or 'unknown'} was not found")
        saved = dict(json_safe(decision))
        decision_id = str(saved.get("id") or uuid.uuid4())
        created_at = str(saved.get("created_at") or _now())
        saved.update({
            "id": decision_id,
            "analysis_id": analysis_id,
            "workspace_id": wid,
            "created_at": created_at,
        })
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_cost_decisions
                  (id, workspace_id, analysis_id, created_at, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (decision_id, wid, analysis_id, created_at, json.dumps(saved)),
            )
            conn.commit()
        return saved

    def list_cost_decisions(
        self, *, workspace_id: str, analysis_id: str
    ) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        aid = str(analysis_id or "").strip()
        if not aid or not self.get_report(aid, workspace_id=wid):
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM migration_cost_decisions
                WHERE workspace_id = %s AND analysis_id = %s
                ORDER BY created_at DESC
                """,
                (wid, aid),
            ).fetchall()
        records = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, dict):
                records.append(dict(payload))
        return records

    def create_supply_scenario(
        self, scenario: dict[str, Any], *, workspace_id: str
    ) -> dict[str, Any]:
        """Persist an immutable supply scenario linked to its saved BOM report."""
        wid = self._require_workspace(workspace_id)
        analysis_id = str(scenario.get("analysis_id") or "").strip()
        if not analysis_id or not self.get_report(analysis_id, workspace_id=wid):
            raise WorkspaceAccessError(f"analysis {analysis_id or 'unknown'} was not found")
        saved = dict(json_safe(scenario))
        scenario_id = str(saved.get("id") or uuid.uuid4())
        created_at = str(saved.get("created_at") or _now())
        saved.update({
            "id": scenario_id,
            "analysis_id": analysis_id,
            "workspace_id": wid,
            "created_at": created_at,
        })
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_supply_scenarios
                  (id, workspace_id, analysis_id, created_at, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (scenario_id, wid, analysis_id, created_at, json.dumps(saved)),
            )
            conn.commit()
        return saved

    def list_supply_scenarios(
        self, *, workspace_id: str, analysis_id: str
    ) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        aid = str(analysis_id or "").strip()
        if not aid or not self.get_report(aid, workspace_id=wid):
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM migration_supply_scenarios
                WHERE workspace_id = %s AND analysis_id = %s
                ORDER BY created_at DESC
                """,
                (wid, aid),
            ).fetchall()
        records = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, dict):
                records.append(dict(payload))
        return records

    def create_developer_webhook(self, row: dict[str, Any]) -> dict[str, Any]:
        wid = self._require_workspace(str(row.get("workspace_id") or ""))
        webhook_id = str(row.get("id") or uuid.uuid4())
        with self._connect() as conn:
            saved = conn.execute(
                """
                INSERT INTO migration_developer_webhooks
                  (id, workspace_id, name, endpoint_ciphertext,
                   signing_secret_ciphertext, event_types, active, created_by)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, TRUE, %s)
                RETURNING *
                """,
                (
                    webhook_id, wid, str(row.get("name") or ""),
                    str(row.get("endpoint_ciphertext") or ""),
                    str(row.get("signing_secret_ciphertext") or ""),
                    json.dumps(row.get("event_types") or []),
                    str(row.get("created_by") or ""),
                ),
            ).fetchone()
            conn.commit()
        result = dict(saved or {})
        for key in ("created_at", "updated_at"):
            if hasattr(result.get(key), "isoformat"):
                result[key] = result[key].isoformat()
        return result

    def list_developer_webhooks(self, workspace_id: str) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM migration_developer_webhooks WHERE workspace_id = %s ORDER BY created_at DESC",
                (wid,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in ("created_at", "updated_at"):
                if hasattr(item.get(key), "isoformat"):
                    item[key] = item[key].isoformat()
            result.append(item)
        return result

    def get_developer_webhook(self, workspace_id: str, webhook_id: str) -> dict[str, Any] | None:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM migration_developer_webhooks WHERE workspace_id = %s AND id = %s",
                (wid, str(webhook_id or "")),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        for key in ("created_at", "updated_at"):
            if hasattr(item.get(key), "isoformat"):
                item[key] = item[key].isoformat()
        return item

    def delete_developer_webhook(self, workspace_id: str, webhook_id: str) -> bool:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE migration_developer_webhooks SET active = FALSE, updated_at = NOW() "
                "WHERE workspace_id = %s AND id = %s AND active = TRUE",
                (wid, str(webhook_id or "")),
            )
            if cursor.rowcount == 1:
                conn.execute(
                    "UPDATE migration_developer_webhook_deliveries "
                    "SET status = 'failed', failure_code = 'webhook_disabled', updated_at = NOW() "
                    "WHERE workspace_id = %s AND webhook_id = %s AND status IN ('pending', 'processing')",
                    (wid, str(webhook_id or "")),
                )
            conn.commit()
            return cursor.rowcount == 1

    def queue_developer_webhook_event(
        self, *, workspace_id: str, event_id: str, event_type: str,
        payload: dict[str, Any], webhook_id: str | None = None,
    ) -> int:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            query = "SELECT id, event_types FROM migration_developer_webhooks WHERE workspace_id = %s AND active = TRUE"
            params: tuple[Any, ...] = (wid,)
            if webhook_id:
                query += " AND id = %s"
                params += (str(webhook_id),)
            hooks = conn.execute(query, params).fetchall()
            created = 0
            for hook in hooks:
                events = hook.get("event_types") or []
                if isinstance(events, str):
                    try:
                        events = json.loads(events)
                    except json.JSONDecodeError:
                        events = []
                if event_type not in events and not (
                    event_type == "webhook.test" and webhook_id and str(hook.get("id") or "") == str(webhook_id)
                ):
                    continue
                inserted = conn.execute(
                    """
                    INSERT INTO migration_developer_webhook_deliveries
                      (id, workspace_id, webhook_id, event_id, event_type, payload)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (webhook_id, event_id) DO NOTHING
                    RETURNING id
                    """,
                    (
                        str(uuid.uuid4()), wid, str(hook["id"]), str(event_id),
                        str(event_type), json.dumps(payload, ensure_ascii=False, default=str),
                    ),
                ).fetchone()
                created += 1 if inserted else 0
            conn.commit()
        return created

    def list_due_developer_webhook_deliveries(
        self, *, workspace_id: str | None = None, webhook_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.execute(
                "UPDATE migration_developer_webhook_deliveries "
                "SET status = 'pending', next_attempt_at = NOW(), updated_at = NOW() "
                "WHERE status = 'processing' AND updated_at < NOW() - INTERVAL '5 minutes'"
            )
            rows = conn.execute(
                """
                WITH due AS (
                  SELECT delivery.id
                    FROM migration_developer_webhook_deliveries AS delivery
                    JOIN migration_developer_webhooks AS hook
                      ON hook.id = delivery.webhook_id
                     AND hook.workspace_id = delivery.workspace_id
                   WHERE delivery.status = 'pending'
                     AND delivery.next_attempt_at <= NOW()
                     AND hook.active = TRUE
                     AND (%s::text IS NULL OR delivery.workspace_id = %s)
                     AND (%s::text IS NULL OR delivery.webhook_id = %s)
                   ORDER BY delivery.created_at
                   LIMIT %s
                   FOR UPDATE OF delivery SKIP LOCKED
                )
                UPDATE migration_developer_webhook_deliveries AS delivery
                   SET status = 'processing', updated_at = NOW()
                  FROM due, migration_developer_webhooks AS hook
                 WHERE delivery.id = due.id
                   AND hook.id = delivery.webhook_id
                   AND hook.workspace_id = delivery.workspace_id
                RETURNING delivery.*, hook.endpoint_ciphertext, hook.signing_secret_ciphertext
                """,
                (
                    str(workspace_id) if workspace_id else None,
                    str(workspace_id or ""),
                    str(webhook_id) if webhook_id else None,
                    str(webhook_id or ""),
                    max(1, min(int(limit), 500)),
                ),
            ).fetchall()
            conn.commit()
        result = []
        for row in rows:
            item = dict(row)
            if isinstance(item.get("payload"), str):
                try:
                    item["payload"] = json.loads(item["payload"])
                except json.JSONDecodeError:
                    item["payload"] = None
            for key in ("created_at", "updated_at", "next_attempt_at", "delivered_at"):
                if hasattr(item.get(key), "isoformat"):
                    item[key] = item[key].isoformat()
            result.append(item)
        return result

    def finish_developer_webhook_delivery(
        self, delivery_id: str, *, delivered: bool, response_status: int | None,
        failure_code: str, retry_delay_seconds: int, max_attempts: int,
    ) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE migration_developer_webhook_deliveries
                   SET attempt_count = attempt_count + 1,
                       status = CASE
                         WHEN %s THEN 'delivered'
                         WHEN attempt_count + 1 >= %s THEN 'failed'
                         ELSE 'pending'
                       END,
                       next_attempt_at = CASE
                         WHEN %s OR attempt_count + 1 >= %s THEN next_attempt_at
                         ELSE NOW() + (%s * INTERVAL '1 second')
                       END,
                       response_status = %s,
                       failure_code = CASE WHEN %s THEN NULL ELSE %s END,
                       delivered_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                       updated_at = NOW()
                 WHERE id = %s AND status = 'processing'
                 RETURNING status
                """,
                (
                    bool(delivered), max(1, int(max_attempts)), bool(delivered),
                    max(1, int(max_attempts)), max(1, int(retry_delay_seconds)),
                    response_status, bool(delivered), str(failure_code or "delivery_error"),
                    bool(delivered), str(delivery_id or ""),
                ),
            ).fetchone()
            conn.commit()
        return str(row["status"]) if row else "failed"

    def list_developer_webhook_deliveries(self, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, webhook_id, event_id, event_type, status, attempt_count,
                       response_status, failure_code, created_at, updated_at, delivered_at
                  FROM migration_developer_webhook_deliveries
                 WHERE workspace_id = %s
                 ORDER BY created_at DESC
                 LIMIT %s
                """,
                (wid, max(1, min(int(limit), 200))),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in ("created_at", "updated_at", "delivered_at"):
                if hasattr(item.get(key), "isoformat"):
                    item[key] = item[key].isoformat()
            result.append(item)
        return result

    def get_developer_webhook_delivery(
        self, workspace_id: str, webhook_id: str, event_id: str
    ) -> dict[str, Any] | None:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, webhook_id, event_id, event_type, status, attempt_count,
                       response_status, failure_code, created_at, updated_at, delivered_at
                  FROM migration_developer_webhook_deliveries
                 WHERE workspace_id = %s AND webhook_id = %s AND event_id = %s
                """,
                (wid, str(webhook_id or ""), str(event_id or "")),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        for key in ("created_at", "updated_at", "delivered_at"):
            if hasattr(item.get(key), "isoformat"):
                item[key] = item[key].isoformat()
        return item

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
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM migration_decision_records WHERE workspace_id = %s AND id = %s",
                (wid, str(decision_record_id or "").strip()),
            ).fetchone()
            if not exists:
                raise WorkspaceAccessError("Decision record was not found.")
            conn.execute(
                """
                INSERT INTO migration_decision_record_approvers
                  (token_hash, workspace_id, decision_record_id, created_by, email, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s::timestamptz)
                """,
                (token_hash, wid, decision_record_id, created_by, email, expires_at),
            )
            conn.commit()

    def get_decision_record_approver(self, token_hash: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT approver.email, approver.status, approver.expires_at,
                       approver.response_rationale, approver.responded_at,
                       decision.payload
                  FROM migration_decision_record_approvers AS approver
                  JOIN migration_decision_records AS decision
                    ON decision.id = approver.decision_record_id
                   AND decision.workspace_id = approver.workspace_id
                 WHERE approver.token_hash = %s
                   AND approver.status <> 'revoked'
                   AND approver.expires_at > NOW()
                """,
                (str(token_hash or "").strip(),),
            ).fetchone()
        if not row:
            return None
        record = row["payload"]
        if isinstance(record, str):
            record = json.loads(record)
        expires = row["expires_at"]
        responded = row["responded_at"]
        return {
            "email": str(row["email"]),
            "status": str(row["status"]),
            "response_rationale": row["response_rationale"],
            "responded_at": responded.isoformat() if hasattr(responded, "isoformat") else responded,
            "record": dict(record) if isinstance(record, dict) else {},
            "expires_at": expires.isoformat() if hasattr(expires, "isoformat") else expires,
        }

    def list_decision_record_approvers(
        self, *, workspace_id: str, status: str = "pending"
    ) -> list[dict[str, Any]]:
        wid = self._require_workspace(workspace_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT decision_record_id, status, expires_at
                  FROM migration_decision_record_approvers
                 WHERE workspace_id = %s AND status = %s AND expires_at > NOW()
                 ORDER BY created_at DESC
                """,
                (wid, str(status or "pending").strip().lower()),
            ).fetchall()
        return [
            {
                "decision_record_id": str(row["decision_record_id"]),
                "status": str(row["status"]),
                "expires_at": row["expires_at"].isoformat()
                if hasattr(row["expires_at"], "isoformat") else row["expires_at"],
            }
            for row in rows
        ]

    def respond_to_decision_record_approver(
        self, token_hash: str, *, decision: str, rationale: str
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE migration_decision_record_approvers
                   SET status = %s, response_rationale = %s, responded_at = NOW()
                 WHERE token_hash = %s AND status = 'pending' AND expires_at > NOW()
                RETURNING token_hash
                """,
                (decision, rationale, str(token_hash or "").strip()),
            ).fetchone()
            conn.commit()
        return bool(row)

    def revoke_decision_record_approver(self, token_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE migration_decision_record_approvers SET status = 'revoked' WHERE token_hash = %s AND status = 'pending'",
                (str(token_hash or "").strip(),),
            )
            conn.commit()

    def find_account_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id AS user_id, email FROM migration_users
                 WHERE LOWER(email) = LOWER(%s)
                 LIMIT 1
                """,
                (str(email or "").strip(),),
            ).fetchone()
        return dict(row) if row else None

    def get_account_entitlement_overrides(self, user_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT feature_overrides FROM migration_account_entitlement_overrides WHERE user_id = %s",
                (str(user_id or "").strip(),),
            ).fetchone()
        if not row:
            return {}
        value = row["feature_overrides"]
        if isinstance(value, str):
            value = json.loads(value)
        return value if isinstance(value, dict) else {}

    def set_account_entitlement_overrides(
        self, *, user_id: str, feature_overrides: dict[str, Any], updated_by: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO migration_account_entitlement_overrides
                  (user_id, feature_overrides, updated_by, updated_at)
                VALUES (%s, %s::jsonb, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                  feature_overrides = EXCLUDED.feature_overrides,
                  updated_by = EXCLUDED.updated_by,
                  updated_at = NOW()
                """,
                (str(user_id or "").strip(), json.dumps(feature_overrides), str(updated_by or "").strip()),
            )
            conn.commit()

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
            created_at = str(saved.get("created_at") or _now())
            saved.update(
                {
                    "id": quote_id,
                    "quote_id": quote_id,
                    "workspace_id": wid,
                    "created_at": created_at,
                }
            )
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO migration_procurement_quotes
                      (id, workspace_id, analysis_id, requested_mpn,
                       requested_manufacturer, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        quote_id,
                        wid,
                        analysis_id,
                        str(saved.get("requested_mpn") or ""),
                        str(saved.get("requested_manufacturer") or ""),
                        created_at,
                        json.dumps(saved),
                    ),
                )
                conn.commit()
            return saved

    def create_procurement_quotes(
        self, quotes: list[dict[str, Any]], *, workspace_id: str
    ) -> list[dict[str, Any]]:
        """Insert a validated quote batch in one Postgres transaction."""
        wid = self._require_workspace(workspace_id)
        if not quotes:
            return []
        analysis_id = str(quotes[0].get("analysis_id") or "").strip()
        if not analysis_id or not self.get_report(analysis_id, workspace_id=wid):
            raise WorkspaceAccessError(f"analysis {analysis_id} was not found")
        if any(str(quote.get("analysis_id") or "").strip() != analysis_id for quote in quotes):
            raise ValueError("A quote batch must belong to one saved analysis.")
        saved_rows: list[dict[str, Any]] = []
        with _LOCK:
            with self._connect() as conn:
                values = []
                for quote in quotes:
                    saved = dict(quote)
                    quote_id = str(saved.get("quote_id") or uuid.uuid4())
                    created_at = str(saved.get("created_at") or _now())
                    saved.update(
                        {
                            "id": quote_id,
                            "quote_id": quote_id,
                            "workspace_id": wid,
                            "created_at": created_at,
                        }
                    )
                    saved_rows.append(saved)
                    values.append(
                        (
                            quote_id,
                            wid,
                            analysis_id,
                            str(saved.get("requested_mpn") or ""),
                            str(saved.get("requested_manufacturer") or ""),
                            created_at,
                            json.dumps(saved),
                        )
                    )
                conn.executemany(
                    """
                    INSERT INTO migration_procurement_quotes
                      (id, workspace_id, analysis_id, requested_mpn,
                       requested_manufacturer, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    values,
                )
                conn.commit()
        return saved_rows

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
        mpn = str(requested_mpn or "").strip()
        maker = str(requested_manufacturer or "").strip()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM migration_procurement_quotes
                WHERE workspace_id = %s AND analysis_id = %s
                  AND (%s = '' OR LOWER(requested_mpn) = LOWER(%s))
                  AND (%s = '' OR LOWER(requested_manufacturer) = LOWER(%s))
                ORDER BY created_at DESC
                """,
                (wid, aid, mpn, mpn, maker, maker),
            ).fetchall()
        result = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            if isinstance(payload, dict):
                result.append(dict(payload))
        return result

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

    def home_dashboard(
        self, *, workspace_id: str, production: bool = False
    ) -> dict[str, Any]:
        wid = self._require_workspace(workspace_id)
        analyses = customer_visible_analyses(
            self.list_reports(workspace_id=wid), production=production
        )
        projects = customer_visible_projects(
            self.list_projects(workspace_id=wid), analyses, production=production
        )
        with self._connect() as conn:
            bom_count = (
                sum(int(project.get("bom_count") or 0) for project in projects)
                if production
                else conn.execute(
                    "SELECT COUNT(*) AS c FROM migration_boms WHERE workspace_id = %s",
                    (wid,),
                ).fetchone()["c"]
            )
            awaiting_approvals = int(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT decision_record_id) AS c
                      FROM migration_decision_record_approvers
                     WHERE workspace_id = %s
                       AND status = 'pending'
                       AND expires_at > NOW()
                    """,
                    (wid,),
                ).fetchone()["c"]
                or 0
            )
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
        priority_severity_counts = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "needs_verification": 0,
        }
        for item in priority:
            level = str(item.get("risk_level") or "").strip().casefold()
            bucket = next(
                (
                    candidate
                    for candidate in ("critical", "high", "medium", "low")
                    if candidate in level
                ),
                "needs_verification",
            )
            priority_severity_counts[bucket] += 1
        open_blockers = (
            priority_severity_counts["critical"]
            + priority_severity_counts["high"]
        )
        next_actions = [
            {
                "title": "Review saved BOMs and assembly risk",
                "detail": "Open saved analyses or inspect the latest nested BOM risk.",
                "links": [
                    {"label": "Open saved BOMs", "href": "/reports"},
                    {
                        "label": "Review latest assembly risk",
                        "href": analyses[0]["id"] if analyses else "/bom-analyzer",
                        "href_kind": "report" if analyses else "route",
                    },
                ],
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
            "mode": "workspace-home",
            "workspace_id": wid,
            "persistence": "migration-postgres-store",
            "metrics": {
                "active_projects": len(projects),
                "saved_boms": int(bom_count),
                "saved_analyses": len(analyses),
                "priority_items": len(priority),
                "open_blockers": open_blockers,
                "awaiting_approvals": awaiting_approvals,
            },
            "projects": projects,
            "recent_analyses": analyses[:12],
            "priority_risks": priority,
            "priority_severity_counts": priority_severity_counts,
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
                conflict = conn.execute(
                    """
                    SELECT 1 FROM migration_projects
                    WHERE workspace_id = %s AND LOWER(name) = LOWER(%s) AND id <> %s
                    """,
                    (wid, new_name, project_id),
                ).fetchone()
                if conflict:
                    raise ValueError("A project with this name already exists.")
                now = _now()
                conn.execute(
                    """
                    UPDATE migration_projects
                    SET name = %s, updated_at = %s
                    WHERE id = %s AND workspace_id = %s
                    """,
                    (new_name, now, project_id, wid),
                )
                linked = conn.execute(
                    """
                    SELECT id, bom_name FROM migration_analyses
                    WHERE project_id = %s AND workspace_id = %s
                    """,
                    (project_id, wid),
                ).fetchall()
                for analysis in linked:
                    aid = str(analysis["id"])
                    title = analysis_title_for_upload(
                        new_name, str(analysis.get("bom_name") or "Saved BOM")
                    )
                    conn.execute(
                        """
                        UPDATE migration_analyses SET project_name = %s, updated_at = %s
                        WHERE id = %s AND workspace_id = %s
                        """,
                        (title, now, aid, wid),
                    )
                    report_row = conn.execute(
                        """
                        SELECT payload FROM migration_reports
                        WHERE id = %s AND workspace_id = %s
                        """,
                        (aid, wid),
                    ).fetchone()
                    if report_row:
                        payload = report_row["payload"]
                        if isinstance(payload, str):
                            payload = json.loads(payload)
                        payload = dict(payload or {})
                        payload["project_name"] = title
                        conn.execute(
                            """
                            UPDATE migration_reports SET payload = %s::jsonb, updated_at = %s
                            WHERE id = %s AND workspace_id = %s
                            """,
                            (json.dumps(payload), now, aid, wid),
                        )
                conn.commit()
                updated = dict(row)
                updated["name"] = new_name
                updated["updated_at"] = now
                updated["id"] = str(updated["id"])
                if hasattr(updated.get("created_at"), "isoformat"):
                    updated["created_at"] = updated["created_at"].isoformat()
                return updated

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
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM migration_boms WHERE id = %s",
                    (bom_id,),
                ).fetchone()
                if not row:
                    raise LookupError(f"BOM {bom_id} not found")
                if row["workspace_id"] != wid:
                    raise WorkspaceAccessError(f"BOM {bom_id} is not in workspace {wid}")
                new_name = str(name if name is not None else row.get("name") or "").strip()
                if not new_name:
                    raise ValueError("name is required")
                target_project_id = str(project_id or row["project_id"])
                project = conn.execute(
                    "SELECT id, name FROM migration_projects WHERE id = %s AND workspace_id = %s",
                    (target_project_id, wid),
                ).fetchone()
                if not project:
                    raise LookupError(f"project {target_project_id} not found")
                conflict = conn.execute(
                    """
                    SELECT 1 FROM migration_boms
                    WHERE workspace_id = %s AND project_id = %s AND LOWER(name) = LOWER(%s)
                      AND id <> %s
                    """,
                    (wid, target_project_id, new_name, bom_id),
                ).fetchone()
                if conflict:
                    raise ValueError("A BOM with this name already exists in this project.")
                project_name = str(project.get("name") or DEFAULT_WORKSPACE_PROJECT)
                now = _now()
                conn.execute(
                    """
                    UPDATE migration_boms SET name = %s, project_id = %s, updated_at = %s
                    WHERE id = %s AND workspace_id = %s
                    """,
                    (new_name, target_project_id, now, bom_id, wid),
                )
                linked = conn.execute(
                    """
                    SELECT id FROM migration_analyses
                    WHERE bom_id = %s AND workspace_id = %s
                    """,
                    (bom_id, wid),
                ).fetchall()
                title = analysis_title_for_upload(project_name, new_name)
                for analysis in linked:
                    aid = str(analysis["id"])
                    conn.execute(
                        """
                        UPDATE migration_analyses
                        SET project_id = %s, bom_name = %s, project_name = %s, updated_at = %s
                        WHERE id = %s AND workspace_id = %s
                        """,
                        (target_project_id, new_name, title, now, aid, wid),
                    )
                    report_row = conn.execute(
                        """
                        SELECT payload FROM migration_reports
                        WHERE id = %s AND workspace_id = %s
                        """,
                        (aid, wid),
                    ).fetchone()
                    if report_row:
                        payload = report_row["payload"]
                        if isinstance(payload, str):
                            payload = json.loads(payload)
                        payload = dict(payload or {})
                        payload["project_id"] = target_project_id
                        payload["bom_name"] = new_name
                        payload["project_name"] = title
                        conn.execute(
                            """
                            UPDATE migration_reports SET payload = %s::jsonb, updated_at = %s
                            WHERE id = %s AND workspace_id = %s
                            """,
                            (json.dumps(payload), now, aid, wid),
                        )
                for affected_project_id in {str(row["project_id"]), target_project_id}:
                    conn.execute(
                        """
                        UPDATE migration_projects SET updated_at = %s
                        WHERE id = %s AND workspace_id = %s
                        """,
                        (now, affected_project_id, wid),
                    )
                conn.commit()
                updated = dict(row)
                updated["name"] = new_name
                updated["project_id"] = target_project_id
                updated["updated_at"] = now
                updated["id"] = str(updated["id"])
                for key in ("created_at",):
                    if hasattr(updated.get(key), "isoformat"):
                        updated[key] = updated[key].isoformat()
                return updated

    def delete_bom(self, bom_id: str, *, workspace_id: str) -> list[str] | None:
        """Delete a BOM and its saved revisions, reports, decisions, and quotes."""
        wid = self._require_workspace(workspace_id)
        with _LOCK:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM migration_boms WHERE id = %s",
                    (bom_id,),
                ).fetchone()
                if not row:
                    return None
                owner = conn.execute(
                    "SELECT workspace_id FROM migration_boms WHERE id = %s",
                    (bom_id,),
                ).fetchone()
                if not owner or owner["workspace_id"] != wid:
                    raise WorkspaceAccessError(f"BOM {bom_id} is not in workspace {wid}")
                rows = conn.execute(
                    """
                    SELECT id FROM migration_analyses
                    WHERE bom_id = %s AND workspace_id = %s
                    """,
                    (bom_id, wid),
                ).fetchall()
                analysis_ids = [str(item["id"]) for item in rows]
                if analysis_ids:
                    alert_rows = conn.execute(
                        """
                        SELECT id FROM migration_monitoring_alerts
                        WHERE workspace_id = %s AND analysis_id = ANY(%s)
                        """,
                        (wid, analysis_ids),
                    ).fetchall()
                    alert_ids = [str(item["id"]) for item in alert_rows]
                    if alert_ids:
                        conn.execute(
                            """
                            DELETE FROM migration_monitoring_email_deliveries
                            WHERE workspace_id = %s AND alert_id = ANY(%s)
                            """,
                            (wid, alert_ids),
                        )
                        conn.execute(
                            """
                            DELETE FROM migration_monitoring_alerts
                            WHERE workspace_id = %s AND id = ANY(%s)
                            """,
                            (wid, alert_ids),
                        )
                    conn.execute(
                        """
                        DELETE FROM migration_monitoring_snapshots
                        WHERE workspace_id = %s AND analysis_id = ANY(%s)
                        """,
                        (wid, analysis_ids),
                    )
                    conn.execute(
                        """
                        DELETE FROM migration_monitoring_refresh_history
                        WHERE workspace_id = %s AND analysis_id = ANY(%s)
                        """,
                        (wid, analysis_ids),
                    )
                    conn.execute(
                        "DELETE FROM migration_decision_records WHERE workspace_id = %s AND analysis_id = ANY(%s)",
                        (wid, analysis_ids),
                    )
                    conn.execute(
                        "DELETE FROM migration_reports WHERE workspace_id = %s AND id = ANY(%s)",
                        (wid, analysis_ids),
                    )
                    conn.execute(
                        "DELETE FROM migration_analyses WHERE workspace_id = %s AND id = ANY(%s)",
                        (wid, analysis_ids),
                    )
                conn.execute(
                    "DELETE FROM migration_boms WHERE id = %s AND workspace_id = %s",
                    (bom_id, wid),
                )
                conn.commit()
                return analysis_ids

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
                    "DELETE FROM migration_decision_records WHERE analysis_id = %s AND workspace_id = %s",
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
