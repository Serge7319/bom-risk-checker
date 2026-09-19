import types
import unittest

from src.workspace_service import accept_my_pending_workspace_invites


class _RpcQuery:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return types.SimpleNamespace(data=self.data)


class _RpcClient:
    def __init__(self, data=None, error=None):
        self.query = _RpcQuery(data=data, error=error)
        self.function = None
        self.arguments = None

    def rpc(self, function, arguments):
        self.function = function
        self.arguments = arguments
        return self.query


class WorkspaceInvitationAcceptanceTests(unittest.TestCase):
    def test_acceptance_returns_workspace_records(self):
        client = _RpcClient(
            data=[{"workspace_id": "ws-1", "workspace_name": "Power Lab"}]
        )
        rows, error = accept_my_pending_workspace_invites(client)
        self.assertEqual(
            client.function,
            "cadivor_accept_my_workspace_invitations",
        )
        self.assertEqual(client.arguments, {})
        self.assertEqual(rows[0]["workspace_id"], "ws-1")
        self.assertIsNone(error)

    def test_missing_rpc_is_reported_as_migration_required(self):
        client = _RpcClient(
            error=RuntimeError(
                "Could not find the function cadivor_accept_my_workspace_invitations"
            )
        )
        rows, error = accept_my_pending_workspace_invites(client)
        self.assertEqual(rows, [])
        self.assertEqual(error, "migration_required")


if __name__ == "__main__":
    unittest.main()
