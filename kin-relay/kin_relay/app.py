"""FastAPI application instance for the kin-relay service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI

from kin_relay.db import create_schema, get_connection
from kin_relay.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the database schema on startup
    db_path = getattr(app.state, "db_path", "relay.db")
    conn = get_connection(db_path)
    try:
        create_schema(conn)
    finally:
        conn.close()
    yield


app = FastAPI(
    title="KIN Relay & Directory Service",
    version="0.1.0",
    lifespan=lifespan,
)

# Default DB path, can be overridden by test suite
app.state.db_path = "relay.db"
app.include_router(router)
