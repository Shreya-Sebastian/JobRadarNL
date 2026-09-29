"""Small load test for the API: concurrent clients hitting a realistic mix of endpoints with varying filters.

Usage: python scripts/loadtest.py [base_url] [seconds] [clients]
Reports throughput and latency percentiles per endpoint. Varying parameters defeat the response cache for a
share of requests, so the numbers reflect real aggregation work, not only cache hits.
"""

from __future__ import annotations

import random
import statistics
import sys
import threading
import time
from collections import defaultdict

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 20
CLIENTS = int(sys.argv[3]) if len(sys.argv) > 3 else 16

ROLES = ["", "backend", "data", "ml", "platform", "frontend"]
LEVELS = ["", "junior", "medior,senior", "intern,junior"]
CITIES = ["", "Amsterdam", "Utrecht,Rotterdam", "Eindhoven", "Remote"]
SKILLS = ["Python", "Kubernetes", "SQL", "AWS", "Java", "Azure"]


def pick_request(rng: random.Random) -> tuple[str, dict]:
    role, level, city = rng.choice(ROLES), rng.choice(LEVELS), rng.choice(CITIES)
    common = {k: v for k, v in (("role", role), ("seniority", level), ("city", city)) if v}
    kind = rng.choices(["overview", "skills", "postings", "cooccurrence", "breakdown", "match", "filters"],
                       weights=[10, 25, 30, 10, 10, 10, 5])[0]
    if kind == "overview":
        return "/api/overview", {}
    if kind == "skills":
        return "/api/skills", {**common, "top": rng.choice([30, 40])}
    if kind == "postings":
        return "/api/postings", {**common, "page": rng.randint(1, 5), "size": 40}
    if kind == "cooccurrence":
        return "/api/cooccurrence", {**common, "top": 28}
    if kind == "breakdown":
        return f"/api/breakdown/{rng.choice(['city', 'seniority', 'role_family', 'company'])}", common
    if kind == "match":
        return "/api/postings", {**common, "sort": "match", "skills_have": ",".join(rng.sample(SKILLS, 3)), "size": 40}
    return "/api/filters", {}


results: dict[str, list[float]] = defaultdict(list)
errors = 0
lock = threading.Lock()
stop = time.monotonic() + SECONDS


def worker(seed: int) -> None:
    global errors
    rng = random.Random(seed)
    with httpx.Client(base_url=BASE, timeout=30) as c:
        while time.monotonic() < stop:
            path, params = pick_request(rng)
            t0 = time.perf_counter()
            try:
                r = c.get(path, params=params)
                ok = r.status_code == 200
            except Exception:
                ok = False
            dt = (time.perf_counter() - t0) * 1000
            key = path if not path.startswith("/api/breakdown") else "/api/breakdown/*"
            if params.get("sort") == "match":
                key += " (match sort)"
            with lock:
                results[key].append(dt)
                if not ok:
                    errors += 1


def main() -> None:
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(CLIENTS)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0
    total = sum(len(v) for v in results.values())
    print(f"{total} requests in {elapsed:.1f}s with {CLIENTS} clients: {total / elapsed:.1f} req/s, {errors} errors\n")
    print(f"{'endpoint':<32}{'n':>6}{'p50 ms':>10}{'p95 ms':>10}{'p99 ms':>10}{'max ms':>10}")
    for key, lat in sorted(results.items()):
        lat.sort()
        q = statistics.quantiles(lat, n=100) if len(lat) >= 100 else None
        p50 = statistics.median(lat)
        p95 = q[94] if q else lat[int(len(lat) * 0.95) - 1]
        p99 = q[98] if q else lat[-1]
        print(f"{key:<32}{len(lat):>6}{p50:>10.0f}{p95:>10.0f}{p99:>10.0f}{lat[-1]:>10.0f}")


if __name__ == "__main__":
    main()
