import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.exc import OperationalError

from app.api import alerts, readings, routes
from app.config import get_settings
from app.log import configure_logging, request_id_var
from app.metrics import DB_ERRORS, HTTP_LATENCY, HTTP_REQUESTS

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)
log = logging.getLogger("app")

app = FastAPI(title="Telemetry Platform", version="0.3.0")
app.include_router(routes.router)
app.include_router(readings.router)
app.include_router(alerts.router)


@app.middleware("http")
async def observe(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    # Accept a caller's request id (e.g. from the load balancer) or mint one.
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id_var.set(rid[:64])
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = rid[:64]
        return response
    finally:
        elapsed = time.perf_counter() - start
        # Route template (/devices/{device_id}/readings), never the raw path: bounded labels.
        route = getattr(request.scope.get("route"), "path", "unmatched")
        if route != "/metrics":
            HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
            HTTP_LATENCY.labels(request.method, route).observe(elapsed)
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "route": route,
                    "status": status,
                    "duration_ms": round(elapsed * 1000, 2),
                },
            )
        request_id_var.reset(token)


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    # Fail fast with a retryable status instead of a 500 and a stack trace to the client.
    DB_ERRORS.inc()
    log.error("database unavailable", extra={"error": type(exc.orig).__name__})
    return JSONResponse(
        {"detail": "database unavailable, retry later"},
        status_code=503,
        headers={"Retry-After": "5"},
    )


@app.get("/livez", tags=["ops"])
def livez() -> dict[str, str]:
    """Process is up. Used by the load balancer, so a DB outage doesn't restart every task."""
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    # Blocked at the public load balancer; scraped from inside the network only.
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
