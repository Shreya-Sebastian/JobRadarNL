import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from radar import auth, mailer, passwords
from radar.config import settings
from radar.db import session_scope
from radar.models import User

H = {"X-Requested-With": "radar"}


@pytest.fixture()
def client(fresh_db):
    mailer.OUTBOX.clear()
    auth._ip_hits.clear()
    auth._fails.clear()
    from radar.api import app

    with TestClient(app) as c:
        yield c


def _link_login(client, email="ada@example.org"):
    client.post("/api/auth/request", json={"email": email}, headers=H)
    body = mailer.OUTBOX[-1].get_body(("plain",)).get_content()
    token = parse_qs(urlparse(next(w for w in body.split() if "token=" in w)).query)["token"][0]
    client.get(f"/auth/verify?token={token}", follow_redirects=False)


def test_password_hashing():
    h = passwords.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert passwords.verify_password("correct horse battery", h)
    assert not passwords.verify_password("wrong horse battery", h) and not passwords.verify_password("x", None)
    assert passwords.hash_password("same password here") != passwords.hash_password("same password here")  # salted
    assert passwords.problem("short") and passwords.problem("aaaaaaaaaaaa") and not passwords.problem("a fine pass 42")


def test_set_a_password_then_sign_in_with_it(client):
    assert client.post("/api/auth/password", json={"email": "ada@example.org", "password": "whatever123"},
                       headers=H).status_code == 401  # no account yet, same answer as a wrong password
    _link_login(client)
    assert client.get("/api/me").json()["has_password"] is False
    assert client.put("/api/me/password", json={"password": "short"}, headers=H).status_code == 422
    assert client.put("/api/me/password", json={"password": "a fine pass 42"}, headers=H).json() == \
        {"has_password": True}
    # changing it needs the current one
    assert client.put("/api/me/password", json={"password": "another pass 99"}, headers=H).status_code == 403
    client.post("/api/auth/logout", headers=H)
    assert client.get("/api/me").json()["signed_in"] is False
    r = client.post("/api/auth/password", json={"email": "ADA@example.org", "password": "a fine pass 42",
                                                "remember": True}, headers=H)
    assert r.status_code == 200 and "Max-Age=7776000" in r.headers["set-cookie"]
    assert client.get("/api/me").json()["email"] == "ada@example.org"
    with session_scope() as s:
        assert s.query(User).one().password_hash.startswith("scrypt$")


def test_wrong_passwords_lock_the_address(client):
    _link_login(client)
    client.put("/api/me/password", json={"password": "a fine pass 42"}, headers=H)
    for _ in range(auth._FAILS_PER_EMAIL):
        assert client.post("/api/auth/password", json={"email": "ada@example.org", "password": "nope nope 1"},
                           headers=H).status_code == 401
    # locked now, even with the right password
    assert client.post("/api/auth/password", json={"email": "ada@example.org", "password": "a fine pass 42"},
                       headers=H).status_code == 429


def _jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig"


@respx.mock
def test_continue_with_google(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    assert client.get("/api/auth/methods").json()["google"] is True
    start = client.get("/auth/google", params={"remember": 1}, follow_redirects=False)
    q = parse_qs(urlparse(start.headers["location"]).query)
    assert start.headers["location"].startswith("https://accounts.google.com/") and q["scope"] == ["openid email"]
    claims = {"iss": "https://accounts.google.com", "aud": "cid.apps.googleusercontent.com", "exp": time.time() + 300,
              "nonce": None, "email": "Grace@Example.org", "email_verified": True}
    nonce = client.cookies.get("radar_oauth").split(".")[1]
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"id_token": _jwt({**claims, "nonce": nonce})}))
    # a forged state (login CSRF) is refused, and the attempt is used up
    bad = client.get("/auth/google/callback", params={"code": "c", "state": "forged"}, follow_redirects=False)
    assert bad.headers["location"] == "/login?google=failed"
    start = client.get("/auth/google", params={"remember": 1}, follow_redirects=False)
    q = parse_qs(urlparse(start.headers["location"]).query)
    nonce = client.cookies.get("radar_oauth").split(".")[1]
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"id_token": _jwt({**claims, "nonce": nonce})}))
    ok = client.get("/auth/google/callback", params={"code": "c", "state": q["state"][0]}, follow_redirects=False)
    assert ok.headers["location"] == "/?login=ok#profile"
    assert client.get("/api/me").json()["email"] == "grace@example.org"


@respx.mock
def test_google_unverified_email_is_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    start = client.get("/auth/google", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    nonce = client.cookies.get("radar_oauth").split(".")[1]
    respx.post("https://oauth2.googleapis.com/token").mock(return_value=httpx.Response(200, json={"id_token": _jwt(
        {"iss": "accounts.google.com", "aud": "cid", "exp": time.time() + 300, "nonce": nonce,
         "email": "x@example.org", "email_verified": False})}))
    r = client.get("/auth/google/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert r.headers["location"] == "/login?google=failed" and client.get("/api/me").json()["signed_in"] is False


def test_google_button_hidden_when_not_configured(client):
    assert client.get("/api/auth/methods").json()["google"] is False
    assert client.get("/auth/google", follow_redirects=False).headers["location"] == "/login?google=off"
