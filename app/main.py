from fastapi import FastAPI

from app.api import alerts, readings, routes

app = FastAPI(title="Telemetry Platform", version="0.2.0")
app.include_router(routes.router)
app.include_router(readings.router)
app.include_router(alerts.router)
