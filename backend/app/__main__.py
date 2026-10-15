"""Allow `python -m app` to boot the dev server with the configured host/port."""

from __future__ import annotations

import uvicorn

from .config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
