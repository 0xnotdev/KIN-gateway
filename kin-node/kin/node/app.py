"""FastAPI application instance for the KIN node."""

from fastapi import FastAPI

from kin.node.routes import router

app = FastAPI(title="KIN Node", version="0.1.0")
app.include_router(router)
