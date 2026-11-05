"""Railway sandbox entry for the Next.js migration API.

Production Streamlit continues to use scripts/railway_start.sh and never
imports this module as a process entrypoint.

Railpack on cadivor-next-api has been observed to ignore railway.toml
startCommand and run `python main.py`. The previous module body only
imported `app` and exited 0 immediately (container status Completed → 502).
When executed as __main__, start a long-running uvicorn server. The `app`
export remains available for `uvicorn main:app`.
"""
from __future__ import annotations

import os

from apps.api.main import app

__all__ = ["app"]


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", "8787"))
    print(
        f"cadivor-migration-api starting via main.py PORT={port}",
        flush=True,
    )
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
