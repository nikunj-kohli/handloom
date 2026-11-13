"""Application entrypoint: FastAPI serving both the API and the built frontend."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles

from . import config, db
from .api import router  # noqa: E402  (imported after config so .env is loaded first)

logger = logging.getLogger("handover")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    db.init_db()
    logger.info("storage ready (%s)", "postgres" if not config.database_is_sqlite() else "sqlite")
    cfg = config.llm_config()
    logger.info("llm provider: %s (%s)", cfg["provider"], cfg["model"])
    if not config.GITHUB_TOKEN:
        logger.warning("GITHUB_TOKEN is not set: live repo ingestion is limited to 60 requests/hour")
    yield


app = FastAPI(
    title=config.APP_NAME,
    version=config.APP_VERSION,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # Reject oversized bodies before Starlette spools them to disk.
    if request.url.path.startswith("/api/"):
        raw_length = request.headers.get("content-length")
        if raw_length and raw_length.isdigit():
            if int(raw_length) > config.MAX_TOTAL_UPLOAD_BYTES + 1_000_000:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": "That request is larger than %s MB."
                        % round(config.MAX_TOTAL_UPLOAD_BYTES / 1_000_000, 1)
                    },
                )

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type:
        response.headers.setdefault("Content-Security-Policy", CSP)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# Errors are answered in one place: users get a readable sentence, logs get the detail.
@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail else "Request failed."
    if exc.status_code == 404:
        detail = "Not found."
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
        headers={key: value for key, value in (exc.headers or {}).items()},
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"detail": "That request was not valid. Check the fields and try again."}
    )


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # Never leak a stack trace or a database message to the browser.
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Nothing was saved; try again."},
    )


app.include_router(router)

DIST = config.ROOT / "frontend" / "dist"
ASSETS = DIST / "assets"

if ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="assets")


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    candidate = DIST / "favicon.svg"
    if candidate.is_file():
        return FileResponse(str(candidate), media_type="image/svg+xml")
    return JSONResponse(status_code=404, content={"detail": "Not found."})


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "Not found."})

    index = DIST / "index.html"
    if not index.is_file():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "The frontend has not been built yet.",
                "how_to_fix": "cd frontend && npm install && npm run build, then reload.",
                "api_health": "/api/health",
            },
        )
    return FileResponse(str(index), media_type="text/html", headers={"Cache-Control": "no-store"})
