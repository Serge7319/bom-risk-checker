"""DigiKey OAuth token cache must single-flight concurrent refreshes."""
from __future__ import annotations

import importlib
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace
from unittest import mock


class DigiKeyTokenRefreshSingleFlightTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.modules.pop("integrations.digikey_client", None)
        self.client = importlib.import_module("integrations.digikey_client")
        self.client._DIGIKEY_CACHED_TOKEN = None
        self.client._DIGIKEY_TOKEN_EXPIRES_AT = 0.0

    def tearDown(self) -> None:
        self.client._DIGIKEY_CACHED_TOKEN = None
        self.client._DIGIKEY_TOKEN_EXPIRES_AT = 0.0

    def test_concurrent_callers_share_one_token_endpoint_request_when_cache_empty(self):
        release_response = threading.Event()
        post_started = threading.Event()
        post_calls: list[object] = []

        def slow_post(url, data=None, timeout=None):
            post_calls.append({"url": url, "data": dict(data or {})})
            post_started.set()
            # Hold the HTTP response until several waiters are blocked on the lock.
            self.assertTrue(release_response.wait(timeout=2.0))
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"access_token": "shared-token", "expires_in": 3600},
            )

        with mock.patch.object(self.client, "get_secret", side_effect=lambda key, required=False: f"secret-{key}"):
            with mock.patch.object(self.client.requests, "post", side_effect=slow_post):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    futures = [
                        pool.submit(self.client.get_digikey_access_token)
                        for _ in range(8)
                    ]
                    self.assertTrue(post_started.wait(timeout=2.0))
                    # Give sibling threads time to queue on the single-flight lock.
                    time.sleep(0.05)
                    release_response.set()
                    tokens = [future.result(timeout=5) for future in as_completed(futures)]

        self.assertEqual(len(post_calls), 1)
        self.assertEqual(post_calls[0]["url"], "https://api.digikey.com/v1/oauth2/token")
        self.assertEqual(post_calls[0]["data"]["grant_type"], "client_credentials")
        self.assertEqual(tokens, ["shared-token"] * 8)
        self.assertEqual(self.client._DIGIKEY_CACHED_TOKEN, "shared-token")

    def test_concurrent_callers_share_one_token_endpoint_request_when_cache_expired(self):
        self.client._DIGIKEY_CACHED_TOKEN = "stale-token"
        self.client._DIGIKEY_TOKEN_EXPIRES_AT = time.monotonic() - 1.0
        post_calls: list[str] = []

        def post(url, data=None, timeout=None):
            post_calls.append(url)
            time.sleep(0.05)
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"access_token": "fresh-token", "expires_in": 3600},
            )

        with mock.patch.object(self.client, "get_secret", side_effect=lambda key, required=False: f"secret-{key}"):
            with mock.patch.object(self.client.requests, "post", side_effect=post):
                with ThreadPoolExecutor(max_workers=6) as pool:
                    tokens = list(
                        pool.map(
                            lambda _: self.client.get_digikey_access_token(),
                            range(6),
                        )
                    )

        self.assertEqual(len(post_calls), 1)
        self.assertEqual(tokens, ["fresh-token"] * 6)


if __name__ == "__main__":
    unittest.main()
