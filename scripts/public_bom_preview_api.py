#!/usr/bin/env python3
"""Local stub API for signed-out public BOM audit Next.js preview smoke."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


PREVIEW = [
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
        "enrichment_pending": False,
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
        "enrichment_pending": False,
    },
]

PENDING = [
    {
        "mpn": f"PENDING{i}",
        "quantity": 1,
        "manufacturer": "",
        "lifecycle": "Pending",
        "risk": "Pending",
        "verified": False,
        "enrichment_pending": True,
        "stock": None,
        "lead_time_weeks": None,
        "supplier_count": None,
    }
    for i in range(3)
]

REPORT = {
    "ok": True,
    "id": "11111111-1111-4111-8111-111111111111",
    "row_count": 5,
    "preview": PREVIEW,
    "remaining_count": 3,
    "remaining_high_risk": 0,
    "remaining_unverified": 3,
    "remaining_pending": 3,
    "preview_enriched_count": 2,
    "full_enriched": False,
    "qa_mode": False,
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

    def _bytes(self, body: bytes, media_type: str, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"'
        )
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._json({"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path.startswith("/public/bom-stress/status"):
            # Optional bearer → qa_verified (stub mirrors API; ignores client flags).
            auth = (self.headers.get("Authorization") or "").strip()
            qa_verified = auth.lower() == "bearer qa-allowlisted-smoke-token"
            self._json(
                {
                    "ok": True,
                    "enabled": True,
                    "preview_rows": 5,
                    "max_rows": 30,
                    "max_bytes": 1_000_000,
                    "turnstile_required": False,
                    "qa_verified": qa_verified,
                    "daily_enriched_row_limit": 500,
                }
            )
            return
        if path.startswith("/public/bom-stress/verified-report/export"):
            auth = self.headers.get("Authorization") or ""
            if not auth.lower().startswith("bearer owner-token"):
                self._json({"detail": "Unauthorized"}, 401)
                return
            qs = parse_qs(urlsplit(self.path).query)
            fmt = (qs.get("format") or ["csv"])[0]
            if fmt == "xlsx":
                self._bytes(b"PK\x03\x04stub-xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "bom-audit-complete.xlsx")
            else:
                self._bytes(b"MPN,Qty\nLM358DR,1\n", "text/csv; charset=utf-8", "bom-audit-complete.csv")
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
            qs = parse_qs(urlsplit(self.path).query)
            report_id = (qs.get("report_id") or [REPORT["id"]])[0]
            self._json(
                {
                    "ok": True,
                    "report": {
                        "id": report_id,
                        "filename": "preview-bom.csv",
                        "row_count": 5,
                        "created_at": "2026-11-14T00:00:00+00:00",
                        "results": PREVIEW + PENDING,
                        "full_enriched": False,
                    },
                }
            )
            return
        self._json({"detail": "Not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or "0")
        _ = self.rfile.read(length) if length else b""
        path = self.path.split("?", 1)[0]
        if path.startswith("/public/bom-stress/audit"):
            self._json(REPORT)
            return
        if path.startswith("/public/bom-stress/lead"):
            self._json(
                {
                    "ok": True,
                    "email": "preview@example.com",
                    "verification_sent": True,
                }
            )
            return
        if path.startswith("/public/bom-stress/complete"):
            auth = self.headers.get("Authorization") or ""
            if not auth.lower().startswith("bearer owner-token"):
                self._json({"detail": "Unauthorized"}, 401)
                return
            completed = [
                {
                    **row,
                    "enrichment_pending": False,
                    "verified": True,
                    "lifecycle": "Active",
                    "risk": "Low",
                    "stock": 10,
                    "lead_time_weeks": 2,
                    "supplier_count": 1,
                    "manufacturer": row.get("manufacturer") or "Stub Mfr",
                }
                for row in PREVIEW + PENDING
            ]
            self._json(
                {
                    "ok": True,
                    "report": {
                        "id": REPORT["id"],
                        "filename": "preview-bom.csv",
                        "row_count": 5,
                        "created_at": "2026-11-14T00:00:00+00:00",
                        "results": completed,
                        "full_enriched": True,
                    },
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
