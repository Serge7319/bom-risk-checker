#!/usr/bin/env python3
"""Local stub API for signed-out public BOM audit Next.js preview smoke."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


REPORT = {
    "ok": True,
    "id": "preview-report-1",
    "row_count": 2,
    "preview": [
        {
            "mpn": "LM358DR",
            "manufacturer": "Texas Instruments",
            "lifecycle": "Active",
            "stock": 1200,
            "stock_evidence": "Reported by DigiKey",
            "lead_time_weeks": 2,
            "lead_time_source": "DigiKey",
            "supplier_count": 1,
            "sources": "DigiKey",
            "supplier_coverage": "1 of 1 configured supplier sources responded successfully.",
            "risk": "Low",
            "verified": True,
        },
        {
            "mpn": "MCP2551-I/SN",
            "manufacturer": "Microchip",
            "lifecycle": "Active",
            "stock": 800,
            "stock_evidence": "Reported by DigiKey",
            "lead_time_weeks": 4,
            "lead_time_source": "DigiKey",
            "supplier_count": 1,
            "sources": "DigiKey",
            "supplier_coverage": "1 of 1 configured supplier sources responded successfully.",
            "risk": "Low",
            "verified": True,
        },
    ],
    "remaining_count": 0,
    "remaining_high_risk": 0,
    "remaining_unverified": 0,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._json({"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path.startswith("/public/bom-stress/status"):
            self._json(
                {
                    "ok": True,
                    "enabled": True,
                    "preview_rows": 5,
                    "max_rows": 30,
                    "max_bytes": 1_000_000,
                }
            )
            return
        if path.startswith("/public/bom-stress/verified-report"):
            auth = self.headers.get("Authorization") or ""
            if not auth.lower().startswith("bearer "):
                self._json({"detail": "Missing bearer token"}, 401)
                return
            token = auth.split(" ", 1)[1].strip()
            if token == "cross-user-token":
                self._json({"detail": "Verified public audit not found."}, 404)
                return
            if token != "owner-token":
                self._json({"detail": "Unauthorized"}, 401)
                return
            self._json(
                {
                    "ok": True,
                    "report": {
                        "id": "preview-report-1",
                        "filename": "preview-bom.csv",
                        "row_count": 2,
                        "created_at": "2026-11-14T00:00:00+00:00",
                        "results": REPORT["preview"],
                    },
                }
            )
            return
        self._json({"detail": "Not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or "0")
        _ = self.rfile.read(length) if length else b""
        if self.path.startswith("/public/bom-stress/audit"):
            self._json(REPORT)
            return
        if self.path.startswith("/public/bom-stress/lead"):
            self._json(
                {
                    "ok": True,
                    "email": "preview@example.com",
                    "verification_sent": True,
                }
            )
            return
        self._json({"detail": "Not found"}, 404)


def main() -> None:
    host = os.environ.get("PUBLIC_BOM_PREVIEW_API_HOST", "127.0.0.1")
    port = int(os.environ.get("PUBLIC_BOM_PREVIEW_API_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"public-bom-preview-api listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
