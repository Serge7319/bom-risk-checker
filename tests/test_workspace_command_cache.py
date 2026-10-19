from src.core.workspace_search import (
    WORKSPACE_COMMAND_CACHE_TTL_SECONDS,
    workspace_command_cache_is_fresh,
)


def test_command_cache_is_reused_briefly_across_routes_in_same_workspace():
    assert workspace_command_cache_is_fresh(
        [{"id": "analysis-1"}],
        fetched_at=100.0,
        cache_scope="user-1:workspace-1",
        expected_scope="user-1:workspace-1",
        now=100.0 + WORKSPACE_COMMAND_CACHE_TTL_SECONDS - 0.1,
    )


def test_command_cache_expires_and_does_not_cross_workspace_or_user():
    commands = [{"id": "analysis-1"}]
    assert not workspace_command_cache_is_fresh(
        commands, 100.0, "user-1:workspace-1", "user-1:workspace-1",
        now=100.0 + WORKSPACE_COMMAND_CACHE_TTL_SECONDS,
    )
    assert not workspace_command_cache_is_fresh(
        commands, 100.0, "user-1:workspace-1", "user-2:workspace-1", now=100.1
    )
    assert not workspace_command_cache_is_fresh(
        commands, 100.0, "user-1:workspace-1", "user-1:workspace-2", now=100.1
    )
