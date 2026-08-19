"""Minimal FastAPI app wired to the DB. Add your idea's real routes here."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import connect, run_migrations

DB_PATH = os.environ.get("APP_DB_PATH", "app.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect(DB_PATH)
    run_migrations(conn)
    app.state.conn = conn
    yield
    conn.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
