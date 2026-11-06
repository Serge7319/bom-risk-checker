"""Disposable-DB verification for anon SECURITY DEFINER revoke migration."""
from __future__ import annotations

from pathlib import Path

import pytest

EMBEDDED = pytest.importorskip("embedded_postgres")
psycopg = pytest.importorskip("psycopg")

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase/migrations/20261105_revoke_anon_security_definer_execute.sql"
)
TRIGGER_HELPER_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase/migrations/20261106_revoke_authenticated_handle_new_user_execute.sql"
)


@pytest.fixture(scope="module")
def disposable_pg(tmp_path_factory):
    root = tmp_path_factory.mktemp("secdef-pg")
    pgdata = root / "pgdata"
    pgdata.mkdir()
    server = EMBEDDED.get_server(pgdata, cleanup_mode="delete")
    uri = server.get_uri(database="postgres")
    assert "railway" not in uri.lower()
    assert "supabase" not in uri.lower()
    yield {"uri": uri, "server": server}
    try:
        server.__exit__(None, None, None)  # type: ignore[attr-defined]
    except Exception:
        pass


def _exec(uri: str, sql: str):
    with psycopg.connect(uri) as conn:
        conn.execute(sql)
        conn.commit()


def _has_privilege(uri: str, role: str, signature: str) -> bool:
    with psycopg.connect(uri) as conn:
        row = conn.execute(
            "select has_function_privilege(%s, %s::regprocedure, 'EXECUTE')",
            (role, signature),
        ).fetchone()
        return bool(row[0])


def test_revoke_migration_keeps_authenticated_app_rpcs_and_blocks_trigger_helpers(disposable_pg):
    uri = disposable_pg["uri"]
    # Roles that exist in Supabase; create locally for privilege checks.
    _exec(
        uri,
        """
        do $$ begin
          create role anon nologin;
        exception when duplicate_object then null;
        end $$;
        do $$ begin
          create role authenticated nologin;
        exception when duplicate_object then null;
        end $$;
        do $$ begin
          create role service_role nologin;
        exception when duplicate_object then null;
        end $$;
        do $$ begin
          create role supabase_auth_admin nologin;
        exception when duplicate_object then null;
        end $$;
        """,
    )
    # Seed representative SECURITY DEFINER functions with overly broad grants.
    _exec(
        uri,
        """
        create or replace function public.cadivor_write_audit_event(
          p_actor text, p_action text, p_payload jsonb
        ) returns void
        language plpgsql
        security definer
        as $$ begin
          -- trigger-only stub
          return;
        end $$;

        create or replace function public.cadivor_audit_engineering_record()
        returns trigger
        language plpgsql
        security definer
        as $$ begin
          return new;
        end $$;

        create or replace function public.cadivor_record_user_activity()
        returns void
        language plpgsql
        security definer
        as $$ begin
          return;
        end $$;

        create or replace function public.cadivor_admin_overview()
        returns jsonb
        language plpgsql
        security definer
        as $$ begin
          return '{}'::jsonb;
        end $$;

        create or replace function public.cadivor_claim_stripe_webhook_event(
          p_event_id text
        ) returns boolean
        language plpgsql
        security definer
        as $$ begin
          return true;
        end $$;

        create schema if not exists auth;
        create table auth.users (id uuid primary key, email text not null);
        create table public.users (id uuid primary key, email text not null);
        create or replace function public.handle_new_user()
        returns trigger
        language plpgsql
        security definer
        set search_path = public
        as $$ begin
          insert into public.users (id, email) values (new.id, new.email)
          on conflict (id) do nothing;
          return new;
        end $$;
        create trigger on_auth_user_created after insert on auth.users
          for each row execute function public.handle_new_user();

        -- Overly broad grants simulating the live advisor finding.
        grant execute on function public.cadivor_write_audit_event(text, text, jsonb) to anon, authenticated;
        grant execute on function public.cadivor_audit_engineering_record() to anon, authenticated;
        grant execute on function public.cadivor_record_user_activity() to anon, authenticated;
        grant execute on function public.cadivor_admin_overview() to anon, authenticated;
        grant execute on function public.cadivor_claim_stripe_webhook_event(text) to anon, authenticated, service_role;
        grant execute on function public.handle_new_user() to anon, authenticated, service_role;
        grant usage on schema auth to supabase_auth_admin;
        grant insert on auth.users to supabase_auth_admin;
        """,
    )

    assert _has_privilege(uri, "anon", "public.cadivor_write_audit_event(text,text,jsonb)")
    assert _has_privilege(uri, "anon", "public.cadivor_record_user_activity()")
    assert _has_privilege(uri, "authenticated", "public.handle_new_user()")

    sql = MIGRATION.read_text(encoding="utf-8")
    _exec(uri, sql)
    helper_sql = TRIGGER_HELPER_MIGRATION.read_text(encoding="utf-8")
    _exec(uri, helper_sql)

    # Trigger-only helpers: neither anon nor authenticated.
    assert not _has_privilege(uri, "anon", "public.cadivor_write_audit_event(text,text,jsonb)")
    assert not _has_privilege(
        uri, "authenticated", "public.cadivor_write_audit_event(text,text,jsonb)"
    )
    assert not _has_privilege(uri, "anon", "public.cadivor_audit_engineering_record()")
    assert not _has_privilege(
        uri, "authenticated", "public.cadivor_audit_engineering_record()"
    )

    # App RPCs: authenticated kept, anon revoked.
    assert _has_privilege(uri, "authenticated", "public.cadivor_record_user_activity()")
    assert _has_privilege(uri, "authenticated", "public.cadivor_admin_overview()")
    assert not _has_privilege(uri, "anon", "public.cadivor_record_user_activity()")
    assert not _has_privilege(uri, "anon", "public.cadivor_admin_overview()")

    # Service-only: anon+authenticated revoked; service_role retained.
    assert not _has_privilege(
        uri, "anon", "public.cadivor_claim_stripe_webhook_event(text)"
    )
    assert not _has_privilege(
        uri, "authenticated", "public.cadivor_claim_stripe_webhook_event(text)"
    )
    assert _has_privilege(
        uri, "service_role", "public.cadivor_claim_stripe_webhook_event(text)"
    )

    # Trigger-only account bootstrap stays attached and functional, while its
    # SECURITY DEFINER function is no longer exposed to signed-in API callers.
    assert not _has_privilege(uri, "anon", "public.handle_new_user()")
    assert not _has_privilege(uri, "authenticated", "public.handle_new_user()")
    assert _has_privilege(uri, "service_role", "public.handle_new_user()")
    _exec(
        uri,
        """
        set role supabase_auth_admin;
        insert into auth.users (id, email)
        values ('00000000-0000-0000-0000-000000000123', 'synthetic@example.test');
        reset role;
        """,
    )
    with psycopg.connect(uri) as conn:
        row = conn.execute(
            "select email from public.users where id = '00000000-0000-0000-0000-000000000123'"
        ).fetchone()
    assert row == ("synthetic@example.test",)
