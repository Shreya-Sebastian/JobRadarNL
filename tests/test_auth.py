from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from radar import auth, mailer
from radar.api import app
from radar.db import session_scope
from radar.models import LoginToken, User, UserData, UserSession

H = {"X-Requested-With": "radar"}


@pytest.fixture()
def client(fresh_db):
    mailer.OUTBOX.clear()
    auth._ip_hits.clear()
    with TestClient(app) as c:
        yield c


def _login(client, email="Ada@Example.org"):
    assert client.post("/api/auth/request", json={"email": email}, headers=H).json()["ok"] is True
    body = mailer.OUTBOX[-1].get_body(("plain",)).get_content()
    link = next(w for w in body.split() if "/auth/verify?token=" in w)
    token = parse_qs(urlparse(link).query)["token"][0]
    r = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?login=ok#profile"
    return token


def test_magic_link_login_sync_and_logout(client):
    assert client.get("/api/me").json() == {"signed_in": False}
    token = _login(client)
    assert client.get("/api/me").json()["email"] == "ada@example.org"
    # the link works once
    r = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert r.headers["location"] == "/?login=expired#profile"
    # only hashes are stored
    with session_scope() as s:
        assert s.query(LoginToken).one().token_hash != token
        assert all(len(x.token_hash) == 64 for x in s.query(UserSession))

    assert client.get("/api/me/data").json() == {"profile": {}, "saved": [], "updated_at": None}
    r = client.put("/api/me/data", json={"profile": {"skills": ["Python"]}, "saved": [3, 1, 3]}, headers=H)
    assert r.status_code == 200
    d = client.get("/api/me/data").json()
    assert d["profile"] == {"skills": ["Python"]} and d["saved"] == [1, 3]
    export = client.get("/api/me/export")
    assert export.json()["email"] == "ada@example.org" and export.json()["saved_job_ids"] == [1, 3]

    assert client.post("/api/auth/logout", headers=H).json() == {"ok": True}
    assert client.get("/api/me").json() == {"signed_in": False}
    assert client.get("/api/me/data").status_code == 401


def test_state_changes_need_the_page_header(client):
    _login(client)
    assert client.put("/api/me/data", json={"profile": {}, "saved": []}).status_code == 403
    assert client.delete("/api/me").status_code == 403
    assert client.post("/api/auth/request", json={"email": "a@b.nl"}).status_code == 403


def test_delete_account_removes_everything(client):
    _login(client)
    client.put("/api/me/data", json={"profile": {"skills": ["Go"]}, "saved": [7]}, headers=H)
    assert client.delete("/api/me", headers=H).json() == {"ok": True}
    assert client.get("/api/me").json() == {"signed_in": False}
    with session_scope() as s:
        assert s.query(User).count() == 0 and s.query(UserData).count() == 0
        assert s.query(UserSession).count() == 0 and s.query(LoginToken).count() == 0


def test_login_requests_are_rate_limited_without_revealing_it(client):
    for _ in range(auth.MAX_PER_EMAIL_PER_HOUR + 3):
        assert client.post("/api/auth/request", json={"email": "bob@example.org"}, headers=H).status_code == 200
    assert len(mailer.OUTBOX) == auth.MAX_PER_EMAIL_PER_HOUR
    assert client.post("/api/auth/request", json={"email": "not-an-address"}, headers=H).status_code == 422


def test_expired_links_and_sessions(client):
    _login(client)
    with session_scope() as s:
        for row in s.query(UserSession):
            row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    assert client.get("/api/me").json() == {"signed_in": False}

    client.post("/api/auth/request", json={"email": "cy@example.org"}, headers=H)
    body = mailer.OUTBOX[-1].get_body(("plain",)).get_content()
    token = parse_qs(urlparse(next(w for w in body.split() if "token=" in w)).query)["token"][0]
    with session_scope() as s:
        s.query(LoginToken).filter(LoginToken.email == "cy@example.org").one().expires_at = datetime.utcnow()
    assert client.get(f"/auth/verify?token={token}", follow_redirects=False).headers["location"].endswith("expired#profile")


def test_cleanup_removes_expired_state_and_inactive_accounts(client):
    _login(client)
    with session_scope() as s:
        s.query(User).one().last_login_at = datetime.utcnow() - timedelta(days=auth.INACTIVE_DAYS + 1)
        for row in s.query(UserSession):
            row.expires_at = datetime.utcnow() - timedelta(days=1)
        for row in s.query(LoginToken):
            row.created_at = datetime.utcnow() - timedelta(days=3)
    with session_scope() as s:
        assert auth.cleanup(s) == {"sessions_removed": 1, "tokens_removed": 1, "accounts_removed": 1}
        assert s.query(User).count() == 0


def test_privacy_page_in_both_languages(client):
    assert "Your rights" in client.get("/privacy").text
    assert '<html lang="nl">' in client.get("/nl/privacy").text


def test_console_backend_says_no_mail_was_sent_and_dev_links_need_opt_in(client, monkeypatch):
    from radar.config import settings

    r = client.post("/api/auth/request", json={"email": "dev@example.org"}, headers=H).json()
    assert r == {"ok": True, "delivery": "console"}  # no link unless explicitly enabled
    monkeypatch.setattr(settings, "dev_login_links", True)
    monkeypatch.setattr(auth, "_ip_allowed", lambda ip: True)
    # the test client is not a loopback address, so still no link
    assert "dev_link" not in client.post("/api/auth/request", json={"email": "dev@example.org"}, headers=H).json()
    monkeypatch.setattr(settings, "mail_backend", "smtp")
    monkeypatch.setattr(mailer, "send", lambda *a, **k: None)
    r = client.post("/api/auth/request", json={"email": "dev2@example.org"}, headers=H).json()
    assert r == {"ok": True}  # a real mail backend never returns the link


def test_a_refused_login_mail_is_a_clear_502(client, monkeypatch):
    import smtplib

    def refuse(*a, **k):
        raise smtplib.SMTPDataError(554, b"Message rejected: Email address is not verified.")

    monkeypatch.setattr(mailer, "send", refuse)
    r = client.post("/api/auth/request", json={"email": "sandbox@example.org"}, headers=H)
    assert r.status_code == 502 and r.json()["detail"] == "the login e-mail could not be sent"
