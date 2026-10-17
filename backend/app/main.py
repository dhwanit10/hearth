"""FastAPI application factory and entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, db
from .config import settings
from .gemini import llm_status
from .routes import router as api_router
from .ws import router as ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("hearth")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    status = llm_status()
    logger.info("Hearth %s starting", __version__)
    logger.info("Database ready: %s (PostgreSQL)", settings.database_name)
    if status["mode"] == "gemini":
        logger.info(
            "LLM: Gemini model=%s thinking=%s",
            status["model"],
            status["thinkingLevel"],
        )
    else:
        logger.warning(
            "LLM: DEMO MODE - GEMINI_API_KEY is not set, replies come from the "
            "offline engine. Add a key to backend/.env for real Gemini answers."
        )
    yield
    logger.info("Hearth shutting down")


app = FastAPI(
    title="Hearth API",
    description=(
        "Companion chat backend: persistent conversation history in PostgreSQL, "
        "persona driven prompting, and token streaming over WebSockets."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ws_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": "Hearth API",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/health",
    }
