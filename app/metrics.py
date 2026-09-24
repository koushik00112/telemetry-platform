"""Prometheus metrics. Label values are bounded (route templates, not raw paths or device ids)."""

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
READINGS_INGESTED = Counter(
    "readings_ingested_total", "Readings received by the API", ["outcome"]
)  # outcome: inserted | duplicate
DB_ERRORS = Counter("db_unavailable_total", "Requests failed because the database was unreachable")

WORKER_PROCESSED = Counter("alert_worker_readings_processed_total", "Readings evaluated")
WORKER_BACKLOG = Gauge("alert_worker_backlog", "Readings waiting for alert evaluation")
WORKER_BATCH_SECONDS = Histogram("alert_worker_batch_seconds", "Time to process one batch")
ALERTS_OPENED = Counter("alerts_opened_total", "Alerts opened")
ALERTS_RESOLVED = Counter("alerts_resolved_total", "Alerts resolved")
