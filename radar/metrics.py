"""Prometheus metrics shared by the API and the workers."""

from prometheus_client import Counter, Gauge, Histogram

FETCHES = Counter("radar_fetches_total", "Board fetches by ATS and outcome", ["ats", "status"])
FETCH_SECONDS = Histogram("radar_fetch_seconds", "Seconds per board fetch", ["ats"],
                          buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300))
POSTINGS_NEW = Counter("radar_postings_new_total", "New postings ingested", ["ats"])
POSTINGS_CLOSED = Counter("radar_postings_closed_total", "Postings closed", ["ats"])
POSTINGS_SEEN = Counter("radar_postings_seen_total", "Postings seen (in scope) per fetch", ["ats"])
LIVE_POSTINGS = Gauge("radar_live_postings", "Live non-duplicate postings", ["kind"])
SOURCES = Gauge("radar_sources", "Sources by status", ["status"])
QUEUE_DEPTH = Gauge("radar_queue_depth", "Jobs waiting per queue", ["queue"])
API_REQUESTS = Counter("radar_api_requests_total", "API requests", ["path", "status"])
API_SECONDS = Histogram("radar_api_seconds", "API latency", ["path"],
                        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5))
