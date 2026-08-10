"""Private bootstrap administration application, isolated from A2A traffic."""

from __future__ import annotations

import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from kin_gateway.config import AdminPlaneSettings
from kin_gateway.upstream.credentials import SecretProvider


def create_admin_app(
    settings: AdminPlaneSettings,
    *,
    secret_provider: SecretProvider | None = None,
) -> FastAPI:
    """Create the private admin surface; it is never mounted on the public app."""

    if settings.authentication == "token" and secret_provider is None:
        raise ValueError("Admin token authentication requires a secret provider")

    app = FastAPI(
        title="KIN Gateway Bootstrap Administration",
        version="0.1.0.dev0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def authenticate_admin(request: Request, call_next):
        if request.url.path.startswith("/admin/"):
            if not _is_authorized(request, settings, secret_provider):
                headers = (
                    {"WWW-Authenticate": "Bearer"}
                    if settings.authentication == "token"
                    else {}
                )
                return JSONResponse(
                    {"detail": "Admin authentication required"},
                    status_code=401,
                    headers=headers,
                )
        return await call_next(request)

    @app.get("/admin/health")
    async def admin_health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _is_authorized(
    request: Request,
    settings: AdminPlaneSettings,
    secret_provider: SecretProvider | None,
) -> bool:
    """Authenticate without placing credential material in errors or logs."""

    if settings.authentication == "mtls":
        ssl_object = request.scope.get("ssl_object")
        if ssl_object is None:
            return False
        try:
            return bool(ssl_object.getpeercert())
        except Exception:
            return False

    authorization = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return False
    if secret_provider is None:
        return False
    try:
        expected = secret_provider.get_secret(
            settings.token_secret_ref or ""
        )
    except Exception:
        return False
    supplied = authorization[len(prefix) :]
    return bool(expected) and secrets.compare_digest(supplied, expected)
