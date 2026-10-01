from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from radar import stats
from radar.api import app

BROWSER = {"user-agent": "Mozilla/5.0 Chrome/130", "accept": "text/html"}


def _row(posted_days_ago, first_seen_days_ago):
    now = datetime.utcnow()
    posted = now - timedelta(days=posted_days_ago) if posted_days_ago is not None else None
    return stats.Row(1, "Data Engineer", "Ex", "Utrecht", False, "https://x/1", posted,
                     now - timedelta(days=first_seen_days_ago), None, "greenhouse")


def test_time_window_uses_the_postings_own_date():
    old_but_newly_seen = _row(40, 1)  # posted 40 days ago, found by the radar yesterday
    no_date = _row(None, 2)
    out = stats.Filters(days=7).apply([old_but_newly_seen, no_date])
    assert out == [no_date]


def test_unknown_pages_get_a_page_and_api_clients_keep_json(fresh_db):
    c = TestClient(app)
    page = c.get("/does-not-exist", headers=BROWSER)
    assert page.status_code == 404 and "text/html" in page.headers["content-type"] and "Back to the jobs" in page.text
    nl = c.get("/nl/vacatures/bestaat-niet", headers=BROWSER)
    assert nl.status_code == 404 and "Terug naar de vacatures" in nl.text
    api = c.get("/api/nope", headers=BROWSER)
    assert api.status_code == 404 and api.json() == {"detail": "Not Found"}
