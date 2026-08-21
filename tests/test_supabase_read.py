"""Tests for idempotent Supabase read transport resilience."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import httpx

from src.supabase_read import (
    DEFAULT_READ_ATTEMPTS,
    SupabaseReadTransportError,
    execute_supabase_read,
)


class SupabaseReadHelperTests(unittest.TestCase):
    def _builder(self, side_effect):
        builder = MagicMock(name="builder")
        builder.execute.side_effect = side_effect
        return builder

    def test_succeeds_on_first_attempt(self) -> None:
        expected = MagicMock(name="response")
        builder = self._builder([expected])

        result = execute_supabase_read(builder, operation="users_select")

        self.assertIs(result, expected)
        builder.execute.assert_called_once_with()

    def test_retries_remote_protocol_error_then_succeeds(self) -> None:
        expected = MagicMock(name="response")
        builder = self._builder(
            [
                httpx.RemoteProtocolError("Server disconnected"),
                expected,
            ]
        )

        with patch("src.supabase_read.time.sleep") as sleep_mock:
            result = execute_supabase_read(builder, operation="users_select", attempts=3)

        self.assertIs(result, expected)
        self.assertEqual(builder.execute.call_count, 2)
        sleep_mock.assert_called_once()

    def test_retry_count_is_bounded(self) -> None:
        builder = self._builder(httpx.RemoteProtocolError("Server disconnected"))

        with patch("src.supabase_read.time.sleep"):
            with self.assertRaises(SupabaseReadTransportError) as ctx:
                execute_supabase_read(builder, operation="users_select", attempts=3)

        self.assertEqual(builder.execute.call_count, 3)
        self.assertIsInstance(ctx.exception.cause, httpx.RemoteProtocolError)

    def test_non_transport_exception_is_not_retried(self) -> None:
        builder = self._builder(ValueError("bad query"))

        with self.assertRaises(ValueError):
            execute_supabase_read(builder, operation="users_select")

        builder.execute.assert_called_once_with()

    def test_default_attempt_count_is_three(self) -> None:
        self.assertEqual(DEFAULT_READ_ATTEMPTS, 3)


if __name__ == "__main__":
    unittest.main()
