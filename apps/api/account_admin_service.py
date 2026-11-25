"""Account lifecycle cleanup for the Next.js migration database.

The migration Postgres database owns workspaces, BOMs, reports, and decisions.
This module removes an account's private workspace data while keeping shared
workspace records and anonymized workspace activity intact.
"""
from __future__ import annotations

from typing import Any

from apps.api import sandbox_auth, team_store, workspace_store


class AccountAdminError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 503) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def validate_migration_account_data(*, user_id: str) -> None:
    """Check durable storage and workspace transfer prerequisites without edits."""
    try:
        auth_store = sandbox_auth.get_auth_store()
        content_store = workspace_store.get_store()
        metadata_store = team_store.get_team_store()
        if any(
            getattr(store, "backend", None) != "postgres"
            for store in (auth_store, content_store, metadata_store)
        ):
            raise AccountAdminError(
                "Account deletion requires the durable migration database.", 503
            )
        database_url = str(getattr(auth_store, "database_url", "") or "").strip()
        if (
            not database_url
            or database_url != str(content_store.database_url).strip()
            or database_url != str(metadata_store.database_url).strip()
        ):
            raise AccountAdminError(
                "Account and workspace storage are not using the same migration database.",
                503,
            )
        auth_store.ensure_schema()
        content_store.ensure_schema()
        metadata_store.ensure_schema()
        import psycopg
        from psycopg.rows import dict_row

        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise AccountAdminError("The account identity is incomplete.", 400)
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            blocker = conn.execute(
                "SELECT ws.workspace_id "
                "FROM migration_workspaces ws "
                "LEFT JOIN migration_workspace_members target_member "
                "ON target_member.workspace_id = ws.workspace_id "
                "AND target_member.user_id = %s "
                "WHERE (ws.owner_id = %s OR target_member.role = 'owner') "
                "AND EXISTS (SELECT 1 FROM migration_workspace_members other_member "
                "WHERE other_member.workspace_id = ws.workspace_id "
                "AND other_member.user_id <> %s) "
                "AND NOT EXISTS (SELECT 1 FROM migration_workspace_members active_member "
                "WHERE active_member.workspace_id = ws.workspace_id "
                "AND active_member.user_id <> %s AND active_member.status = 'active') "
                "LIMIT 1",
                (normalized_user_id, normalized_user_id, normalized_user_id, normalized_user_id),
            ).fetchone()
        if blocker:
            raise AccountAdminError(
                "A shared workspace has no active member to receive ownership. "
                "Restore an active member or change workspace ownership, then retry.",
                409,
            )
    except AccountAdminError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AccountAdminError(
            "Private workspace data could not be checked. The account was not changed.",
            503,
        ) from exc


def delete_migration_account_data(*, user_id: str, email: str) -> dict[str, int]:
    """Erase personal workspace data, retain shared data, and anonymize activity.

    This method is idempotent so an administrator can retry if the separate
    Supabase Auth deletion fails after this transaction commits.
    """
    try:
        auth_store = sandbox_auth.get_auth_store()
        content_store = workspace_store.get_store()
        metadata_store = team_store.get_team_store()
        if any(
            getattr(store, "backend", None) != "postgres"
            for store in (auth_store, content_store, metadata_store)
        ):
            raise AccountAdminError(
                "Account deletion requires the durable migration database.", 503
            )
        database_url = str(getattr(auth_store, "database_url", "") or "").strip()
        if not database_url or database_url != str(content_store.database_url).strip() or database_url != str(metadata_store.database_url).strip():
            raise AccountAdminError(
                "Account and workspace storage are not using the same migration database.",
                503,
            )
        auth_store.ensure_schema()
        content_store.ensure_schema()
        metadata_store.ensure_schema()
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row

        normalized_user_id = str(user_id or "").strip()
        normalized_email = str(email or "").strip().lower()
        if not normalized_user_id or not normalized_email:
            raise AccountAdminError("The account identity is incomplete.", 400)

        private_workspace_ids: list[str] = []
        shared_workspace_ids: list[str] = []
        transferred = 0
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"cadivor.account-deletion:{normalized_user_id}",),
                )
                membership_rows = conn.execute(
                    "SELECT workspace_id, workspace_name, role, status "
                    "FROM migration_workspace_members WHERE user_id = %s FOR UPDATE",
                    (normalized_user_id,),
                ).fetchall()
                owned_rows = conn.execute(
                    "SELECT workspace_id, name, owner_id FROM migration_workspaces "
                    "WHERE owner_id = %s FOR UPDATE",
                    (normalized_user_id,),
                ).fetchall()

                memberships_by_workspace = {
                    str(row["workspace_id"]): row for row in membership_rows
                }
                workspace_ids = sorted(
                    set(memberships_by_workspace)
                    | {str(row["workspace_id"]) for row in owned_rows}
                )
                owned_by_workspace = {
                    str(row["workspace_id"]): row for row in owned_rows
                }

                for workspace_id in workspace_ids:
                    other_members = conn.execute(
                        "SELECT user_id, role, status, workspace_name, created_at "
                        "FROM migration_workspace_members "
                        "WHERE workspace_id = %s AND user_id <> %s "
                        "ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END, "
                        "CASE WHEN role = 'owner' THEN 0 WHEN role = 'admin' THEN 1 ELSE 2 END, "
                        "created_at NULLS LAST, user_id",
                        (workspace_id, normalized_user_id),
                    ).fetchall()
                    target_member = memberships_by_workspace.get(workspace_id) or {}
                    owner_row = owned_by_workspace.get(workspace_id) or {}
                    target_is_owner = (
                        str(owner_row.get("owner_id") or "") == normalized_user_id
                        or str(target_member.get("role") or "").lower() == "owner"
                    )

                    if not other_members:
                        if target_is_owner:
                            private_workspace_ids.append(workspace_id)
                        continue

                    shared_workspace_ids.append(workspace_id)
                    if not target_is_owner:
                        continue
                    active_successors = [
                        row for row in other_members if str(row.get("status") or "") == "active"
                    ]
                    if not active_successors:
                        raise AccountAdminError(
                            "A shared workspace has no active member to receive ownership. "
                            "Restore an active member or change workspace ownership, then retry.",
                            409,
                        )
                    successor = active_successors[0]
                    successor_id = str(successor["user_id"])
                    conn.execute(
                        "UPDATE migration_workspace_members SET role = 'owner' "
                        "WHERE workspace_id = %s AND user_id = %s",
                        (workspace_id, successor_id),
                    )
                    workspace_name = str(
                        owner_row.get("name")
                        or successor.get("workspace_name")
                        or workspace_id
                    )
                    conn.execute(
                        "INSERT INTO migration_workspaces (workspace_id, name, owner_id) "
                        "VALUES (%s, %s, %s) ON CONFLICT (workspace_id) DO UPDATE SET "
                        "owner_id = EXCLUDED.owner_id, updated_at = NOW()",
                        (workspace_id, workspace_name, successor_id),
                    )
                    transferred += 1

                if private_workspace_ids:
                    table_rows = conn.execute(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        "AND table_name LIKE 'migration_%' AND column_name = 'workspace_id' "
                        "GROUP BY table_name ORDER BY table_name"
                    ).fetchall()
                    for row in table_rows:
                        table_name = str(row["table_name"])
                        conn.execute(
                            sql.SQL("DELETE FROM {} WHERE workspace_id = ANY(%s)").format(
                                sql.Identifier(table_name)
                            ),
                            (private_workspace_ids,),
                        )

                if shared_workspace_ids:
                    conn.execute(
                        "UPDATE migration_workspace_activity SET actor_id = NULL, "
                        "actor_name = 'Former member', summary = 'Activity by former member', "
                        "metadata = '{}'::jsonb WHERE workspace_id = ANY(%s) AND actor_id = %s",
                        (shared_workspace_ids, normalized_user_id),
                    )
                    conn.execute(
                        "UPDATE migration_workspace_invites SET invited_by = NULL, "
                        "invited_by_name = NULL, accepted_by = CASE WHEN accepted_by = %s "
                        "THEN NULL ELSE accepted_by END "
                        "WHERE workspace_id = ANY(%s) AND (invited_by = %s OR accepted_by = %s)",
                        (normalized_user_id, shared_workspace_ids, normalized_user_id, normalized_user_id),
                    )
                    conn.execute(
                        "UPDATE migration_decision_record_shares SET created_by = NULL "
                        "WHERE workspace_id = ANY(%s) AND created_by = %s",
                        (shared_workspace_ids, normalized_user_id),
                    )
                    conn.execute(
                        "UPDATE migration_decision_record_approvers SET created_by = NULL "
                        "WHERE workspace_id = ANY(%s) AND created_by = %s",
                        (shared_workspace_ids, normalized_user_id),
                    )

                conn.execute(
                    "DELETE FROM migration_workspace_invites "
                    "WHERE lower(email) = lower(%s)",
                    (normalized_email,),
                )
                conn.execute(
                    "UPDATE migration_decision_record_approvers "
                    "SET email = 'deleted-account@invalid', "
                    "status = CASE WHEN status = 'pending' THEN 'revoked' ELSE status END "
                    "WHERE lower(email) = lower(%s)",
                    (normalized_email,),
                )
                conn.execute(
                    "DELETE FROM migration_customer_profiles WHERE user_id = %s",
                    (normalized_user_id,),
                )
                conn.execute(
                    "DELETE FROM migration_user_preferences WHERE user_id = %s",
                    (normalized_user_id,),
                )
                conn.execute(
                    "UPDATE migration_account_entitlement_overrides "
                    "SET updated_by = 'deleted-account' WHERE updated_by = %s",
                    (normalized_user_id,),
                )
                conn.execute(
                    "DELETE FROM migration_account_entitlement_overrides WHERE user_id = %s",
                    (normalized_user_id,),
                )
                conn.execute(
                    "UPDATE migration_legal_acceptances SET email = 'deleted-account@invalid', "
                    "user_id = NULL, workspace_name = NULL WHERE user_id = %s",
                    (normalized_user_id,),
                )
                conn.execute(
                    "UPDATE migration_legal_acceptances SET email = 'deleted-account@invalid', "
                    "workspace_name = NULL WHERE lower(email) = lower(%s)",
                    (normalized_email,),
                )
                conn.execute(
                    "DELETE FROM migration_user_active_workspace WHERE user_id = %s",
                    (normalized_user_id,),
                )
                conn.execute(
                    "DELETE FROM migration_ai_credit_usage WHERE user_id = %s",
                    (normalized_user_id,),
                )
                conn.execute(
                    "DELETE FROM migration_users WHERE id = %s",
                    (normalized_user_id,),
                )

        return {
            "private_workspaces_deleted": len(private_workspace_ids),
            "shared_workspaces_preserved": len(shared_workspace_ids),
            "shared_workspaces_ownership_transferred": transferred,
        }
    except AccountAdminError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AccountAdminError(
            "Private workspace data could not be cleaned up. The account was not deleted.",
            503,
        ) from exc
