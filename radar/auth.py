"""Passwordless accounts: sign in with a one-time e-mail link.

Why this design:
- No passwords are stored, so none can leak or be reused elsewhere.
- Login tokens and session tokens are random (256 bits) and only their SHA-256 is stored.
- A link works once, for 15 minutes. Requests are rate-limited per e-mail address and per IP address, and the
  response is identical whether or not the address has an account, so the endpoint cannot be used to test which
  e-mail addresses are registered.
- The session cookie is HttpOnly (page scripts cannot read it), SameSite=Lax (not sent on cross-site POSTs) and
  Secure when the site runs on HTTPS. State-changing calls also require a custom header, which a cross-site form
  cannot set, as a second guard against request forgery.
- An account holds only the e-mail address, the profile and the saved jobs. "Delete my account" removes all of it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import smtplib
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from html import escape
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from radar import mailer, passwords
from radar.analytics import client_ip
from radar.config import settings
from radar.models import LoginToken, User, UserData, UserSession

log = logging.getLogger(__name__)
COOKIE = "radar_session"
TOKEN_MINUTES = 15
MAX_PER_EMAIL_PER_HOUR = 5
MAX_PER_IP_PER_HOUR = 20
MAX_DATA_BYTES = 64_000
INACTIVE_DAYS = 730  # accounts nobody has logged in to for two years are removed
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")

router = APIRouter()
_ip_hits: dict[str, deque] = {}
_ip_lock = threading.Lock()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _db():
    from radar.db import new_session

    s = new_session()
    try:
        yield s
    finally:
        s.close()


def _ip_allowed(ip: str) -> bool:
    now = time.monotonic()
    with _ip_lock:
        q = _ip_hits.setdefault(ip, deque())
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= MAX_PER_IP_PER_HOUR:
            return False
        q.append(now)
        return True


def _require_json_header(request: Request) -> None:
    # a cross-site HTML form cannot send this header; fetch() from our own page does
    if request.headers.get("x-requested-with") != "radar":
        raise HTTPException(403, "missing request header")


def current_user(request: Request, session: Session = Depends(_db)) -> User | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    row = session.scalar(select(UserSession).where(UserSession.token_hash == _hash(token)))
    if row is None or row.expires_at < datetime.utcnow():
        return None
    if not row.last_seen_at or datetime.utcnow() - row.last_seen_at > timedelta(hours=1):
        row.last_seen_at = datetime.utcnow()
        session.commit()
    return session.get(User, row.user_id)


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "not signed in")
    return user


class LinkRequest(BaseModel):
    email: str = Field(max_length=254)
    lang: str = "en"
    remember: bool = True  # "keep me signed in on this device"


@router.post("/api/auth/request")
def request_link(body: LinkRequest, request: Request, session: Session = Depends(_db)):
    _require_json_header(request)
    return _issue_link(session, request, body.email, "login", body.remember, body.lang)


class SignupRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=passwords.MAX_LENGTH)
    lang: str = "en"
    remember: bool = True


@router.post("/api/auth/signup")
def signup(body: SignupRequest, request: Request, session: Session = Depends(_db)):
    """Create an account with a password. Nothing is created until the address is confirmed with the e-mailed
    link, so nobody can register (or set a password on) an address they cannot read."""
    _require_json_header(request)
    why = passwords.problem(body.password)
    if why:
        raise HTTPException(422, why)
    return _issue_link(session, request, body.email, "signup", body.remember, body.lang,
                       password_hash=passwords.hash_password(body.password))


class ForgotRequest(BaseModel):
    email: str = Field(max_length=254)
    lang: str = "en"


@router.post("/api/auth/forgot")
def forgot_password(body: ForgotRequest, request: Request, session: Session = Depends(_db)):
    """A reset link: opening it signs in and allows choosing a new password without the old one for 15 minutes."""
    _require_json_header(request)
    return _issue_link(session, request, body.email, "reset", True, body.lang)


def _issue_link(session: Session, request: Request, email: str, purpose: str, remember: bool, lang: str,
                password_hash: str | None = None) -> dict:
    email = email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(422, "that does not look like an e-mail address")
    ip = client_ip(request) or "unknown"  # the visitor, not the proxy in front of the app
    if not _ip_allowed(ip):
        raise HTTPException(429, "too many requests; try again later")
    hour_ago = datetime.utcnow() - timedelta(hours=1)
    recent = session.scalar(select(func.count()).select_from(LoginToken)
                            .where(LoginToken.email == email, LoginToken.created_at >= hour_ago)) or 0
    out: dict = {"ok": True}
    if settings.mail_backend == "console":
        out["delivery"] = "console"  # no mail service configured: say so instead of pretending a mail is on its way
    if recent < MAX_PER_EMAIL_PER_HOUR:
        token = secrets.token_urlsafe(32)
        session.add(LoginToken(token_hash=_hash(token), email=email, ip=ip, remember=remember, purpose=purpose,
                               password_hash=password_hash,
                               expires_at=datetime.utcnow() + timedelta(minutes=TOKEN_MINUTES)))
        session.commit()
        # The link always points at the configured public site, never at the Host header of this request (which
        # a caller controls). Only the console backend, which sends nothing, uses the local address.
        base = str(request.base_url) if settings.mail_backend == "console" else settings.site_url
        try:
            link = _send_link(email, token, "nl" if lang == "nl" else "en", base, purpose)
        except (smtplib.SMTPException, OSError) as e:
            # the mail service refused or could not be reached: say so, and log one line instead of a trace
            log.error("login mail to %s not sent: %s", mailer._mask(email), e)
            raise HTTPException(502, "the login e-mail could not be sent") from None
        if settings.mail_backend == "console" and settings.dev_login_links and ip in {"127.0.0.1", "::1"}:
            out["dev_link"] = link
    # same answer either way, so the endpoint does not reveal who has an account or who is rate-limited
    return out


_MAIL = {
    "en": {
        "login": ("Sign in to {name}", "Click this link to sign in to {name}:"),
        "signup": ("Confirm your e-mail address for {name}",
                   "Click this link to confirm your e-mail address and finish creating your {name} account:"),
        "reset": ("Reset your {name} password", "Click this link to choose a new password for {name}:"),
        "tail": "The link works once and is valid for {m} minutes. If you did not ask for it, you can ignore this "
                "e-mail.",
    },
    "nl": {
        "login": ("Inloggen bij {name}", "Klik op deze link om in te loggen bij {name}:"),
        "signup": ("Bevestig je e-mailadres voor {name}",
                   "Klik op deze link om je e-mailadres te bevestigen en je {name}-account af te maken:"),
        "reset": ("Nieuw wachtwoord voor {name}", "Klik op deze link om een nieuw wachtwoord te kiezen voor {name}:"),
        "tail": "De link werkt één keer en is {m} minuten geldig. Heb je dit niet aangevraagd? Dan kun je deze "
                "e-mail negeren.",
    },
}


def _send_link(email: str, token: str, lang: str, base: str, purpose: str = "login") -> str:
    link = f"{base.rstrip('/')}/auth/verify?token={quote(token)}"
    name = settings.site_name
    t = _MAIL["nl" if lang == "nl" else "en"]
    subject, intro = (x.format(name=name) for x in t.get(purpose, t["login"]))
    text = f"{intro}\n\n{link}\n\n{t['tail'].format(m=TOKEN_MINUTES)}"
    html = "<p>" + escape(text.split("\n\n")[0]) + f'</p><p><a href="{escape(link)}">{escape(link)}</a></p><p>' + \
        escape(text.split("\n\n")[2]) + "</p>"
    mailer.send(email, subject, text, html)
    return link


@router.get("/auth/verify", include_in_schema=False)
def verify(token: str, request: Request, session: Session = Depends(_db)):
    row = session.scalar(select(LoginToken).where(LoginToken.token_hash == _hash(token)))
    now = datetime.utcnow()
    if row is None or row.used_at is not None or row.expires_at <= now:
        return RedirectResponse("/login?expired=1", status_code=303)
    row.used_at = now
    purpose = row.purpose or "login"
    target = "/?login=ok&reset=1#account" if purpose == "reset" else "/?login=ok#profile"
    resp = _sign_in(session, request, row.email, row.remember is not False, RedirectResponse(target, status_code=303),
                    reset=purpose == "reset")
    if purpose == "signup" and row.password_hash:
        # the address is confirmed now, so the password chosen at sign-up takes effect
        user = session.scalar(select(User).where(User.email == row.email))
        user.password_hash, user.password_set_at = row.password_hash, now
        row.password_hash = None
        session.commit()
    return resp


def _local(request: Request) -> bool:
    return request.url.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}


def _sign_in(session: Session, request: Request, email: str, remember: bool, resp: Response,
             reset: bool = False) -> Response:
    """Create the account on first sign-in, open a session and set its cookie on `resp` (every method ends here)."""
    now = datetime.utcnow()
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        session.add(user)
        session.flush()
    user.last_login_at = now
    raw = secrets.token_urlsafe(32)
    # "keep me signed in": a cookie that lasts session_days; otherwise a browser-session cookie that ends when the
    # browser closes, and a server-side session that ends after short_session_hours at the latest
    lifetime = timedelta(days=settings.session_days) if remember else timedelta(hours=settings.short_session_hours)
    session.add(UserSession(token_hash=_hash(raw), user_id=user.id, expires_at=now + lifetime,
                            reset_until=now + timedelta(minutes=TOKEN_MINUTES) if reset else None))
    session.commit()
    # Secure behind a TLS-terminating proxy too (the app then sees http); only a local run gets a plain cookie
    resp.set_cookie(COOKIE, raw, max_age=int(lifetime.total_seconds()) if remember else None, httponly=True,
                    samesite="lax", secure=request.url.scheme == "https" or not _local(request), path="/")
    return resp


# ---------- Continue with Google (OpenID Connect, authorization code flow) ----------
_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_OAUTH_COOKIE = "radar_oauth"


def google_enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _google_redirect_uri(request: Request) -> str:
    # the address Google sends people back to; it must also be registered in the Google Cloud client
    base = str(request.base_url) if _local(request) else settings.site_url
    return base.rstrip("/") + "/auth/google/callback"


@router.get("/auth/google", include_in_schema=False)
def google_start(request: Request, remember: int = 1, lang: str = "en"):
    if not google_enabled():
        return RedirectResponse("/login?google=off", status_code=303)
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    params = {"client_id": settings.google_client_id, "redirect_uri": _google_redirect_uri(request),
              "response_type": "code", "scope": "openid email", "state": state, "nonce": nonce,
              "prompt": "select_account"}
    resp = RedirectResponse(f"{_GOOGLE_AUTH}?{urlencode(params)}", status_code=303)
    # state and nonce tie Google's answer to this browser and this attempt (no login CSRF, no replayed token)
    resp.set_cookie(_OAUTH_COOKIE, f"{state}.{nonce}.{1 if remember else 0}.{'nl' if lang == 'nl' else 'en'}",
                    max_age=600, httponly=True, samesite="lax", secure=not _local(request), path="/auth/google")
    return resp


def _id_token_claims(id_token: str) -> dict:
    """The claims of an ID token received directly from Google's token endpoint over TLS with our client secret;
    OpenID Connect Core 3.1.3.7 allows skipping the signature check in exactly this case. Issuer, audience,
    expiry and nonce are still checked by the caller."""
    payload = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


@router.get("/auth/google/callback", include_in_schema=False)
def google_callback(request: Request, code: str = "", state: str = "", session: Session = Depends(_db)):
    fail = RedirectResponse("/login?google=failed", status_code=303)
    fail.delete_cookie(_OAUTH_COOKIE, path="/auth/google")
    try:
        want_state, nonce, remember, _lang = (request.cookies.get(_OAUTH_COOKIE) or "").split(".")
    except ValueError:
        return fail
    if not code or not google_enabled() or not hmac.compare_digest(state, want_state):
        return fail
    try:
        r = httpx.post(_GOOGLE_TOKEN, timeout=15, data={
            "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
            "redirect_uri": _google_redirect_uri(request), "grant_type": "authorization_code"})
        r.raise_for_status()
        claims = _id_token_claims(r.json()["id_token"])
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        log.warning("google sign-in: token exchange failed")
        return fail
    ok = (claims.get("iss") in ("accounts.google.com", "https://accounts.google.com")
          and claims.get("aud") == settings.google_client_id and claims.get("exp", 0) > time.time()
          and hmac.compare_digest(str(claims.get("nonce", "")), nonce) and claims.get("email_verified") is True
          and _EMAIL.match(str(claims.get("email", ""))))
    if not ok:
        log.warning("google sign-in: rejected ID token claims")
        return fail
    resp = RedirectResponse("/?login=ok#profile", status_code=303)
    resp.delete_cookie(_OAUTH_COOKIE, path="/auth/google")
    return _sign_in(session, request, claims["email"].lower(), remember == "1", resp)


# ---------- passwords (optional, set after signing in once) ----------
_FAILS_PER_EMAIL = 5
_LOCK = timedelta(minutes=15)
_fails: dict[str, deque] = {}
_fails_lock = threading.Lock()


def _locked(email: str) -> bool:
    now = time.monotonic()
    with _fails_lock:
        q = _fails.setdefault(email, deque())
        while q and now - q[0] > _LOCK.total_seconds():
            q.popleft()
        return len(q) >= _FAILS_PER_EMAIL


def _failed(email: str) -> None:
    with _fails_lock:
        _fails.setdefault(email, deque()).append(time.monotonic())


class PasswordLogin(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=passwords.MAX_LENGTH)
    remember: bool = True


@router.post("/api/auth/password")
def password_login(body: PasswordLogin, request: Request, session: Session = Depends(_db)):
    _require_json_header(request)
    email = body.email.strip().lower()
    ip = client_ip(request) or "unknown"  # the visitor, not the proxy in front of the app
    if not _ip_allowed(ip) or _locked(email):
        raise HTTPException(429, "too many attempts; try again in 15 minutes or use an e-mail link")
    user = session.scalar(select(User).where(User.email == email)) if _EMAIL.match(email) else None
    stored = user.password_hash if user and user.password_hash else passwords.DUMMY_HASH
    if not passwords.verify_password(body.password, stored) or user is None or not user.password_hash:
        _failed(email)
        # the same answer whether the address is unknown, has no password or the password is wrong
        raise HTTPException(401, "wrong e-mail address or password")
    with _fails_lock:
        _fails.pop(email, None)
    return _sign_in(session, request, email, body.remember,
                    Response(content='{"ok": true}', media_type="application/json"))


class PasswordChange(BaseModel):
    password: str = Field(default="", max_length=passwords.MAX_LENGTH)
    current: str = Field(default="", max_length=passwords.MAX_LENGTH)


@router.put("/api/me/password")
def set_password(body: PasswordChange, request: Request, user: User = Depends(require_user),
                 session: Session = Depends(_db)):
    _require_json_header(request)
    u = session.get(User, user.id)
    resetting = _reset_allowed(request, session)
    if u.password_hash and not resetting and not passwords.verify_password(body.current, u.password_hash):
        raise HTTPException(403, "the current password is not right")
    why = passwords.problem(body.password)
    if why:
        raise HTTPException(422, why)
    u.password_hash = passwords.hash_password(body.password)
    u.password_set_at = datetime.utcnow()
    if resetting:  # the reset allowance is used up
        session.execute(update(UserSession).where(UserSession.token_hash == _hash(request.cookies.get(COOKIE, "")))
                        .values(reset_until=None))
    session.commit()
    return {"has_password": True}


def _reset_allowed(request: Request, session: Session) -> bool:
    token = request.cookies.get(COOKIE)
    row = session.scalar(select(UserSession).where(UserSession.token_hash == _hash(token))) if token else None
    return bool(row and row.reset_until and row.reset_until > datetime.utcnow())


@router.delete("/api/me/password")
def remove_password(body: PasswordChange, request: Request, user: User = Depends(require_user),
                    session: Session = Depends(_db)):
    _require_json_header(request)
    u = session.get(User, user.id)
    if u.password_hash and not passwords.verify_password(body.current, u.password_hash):
        raise HTTPException(403, "the current password is not right")
    u.password_hash = u.password_set_at = None
    session.commit()
    return {"has_password": False}


@router.get("/api/auth/methods")
def methods():
    return {"google": google_enabled(), "password": True, "link": True}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response, session: Session = Depends(_db)):
    _require_json_header(request)
    token = request.cookies.get(COOKIE)
    if token:
        session.execute(delete(UserSession).where(UserSession.token_hash == _hash(token)))
        session.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/api/me")
def me(request: Request, user: User | None = Depends(current_user), session: Session = Depends(_db)):
    if user is None:
        return {"signed_in": False}
    return {"signed_in": True, "email": user.email, "since": user.created_at.date().isoformat(),
            "has_password": bool(user.password_hash), "can_reset_password": _reset_allowed(request, session)}


class DataBody(BaseModel):
    profile: dict = Field(default_factory=dict)
    saved: list[int] = Field(default_factory=list, max_length=2000)


@router.get("/api/me/data")
def get_data(user: User = Depends(require_user), session: Session = Depends(_db)):
    row = session.get(UserData, user.id)
    if row is None:
        return {"profile": {}, "saved": [], "updated_at": None}
    return {"profile": row.profile or {}, "saved": row.saved or [], "updated_at": row.updated_at.isoformat()}


@router.put("/api/me/data")
def put_data(body: DataBody, request: Request, user: User = Depends(require_user), session: Session = Depends(_db)):
    _require_json_header(request)
    if len(json.dumps(body.profile)) > MAX_DATA_BYTES:
        raise HTTPException(413, "profile too large")
    row = session.get(UserData, user.id)
    if row is None:
        row = UserData(user_id=user.id)
        session.add(row)
    row.profile = body.profile
    row.saved = sorted(set(body.saved))
    row.updated_at = datetime.utcnow()
    session.commit()
    return {"ok": True, "updated_at": row.updated_at.isoformat()}


class AlertsBody(BaseModel):
    frequency: str = Field(pattern="^(off|daily|weekly)$")
    lang: str = "en"


@router.get("/api/me/alerts")
def get_alerts(user: User = Depends(require_user)):
    return {"frequency": user.alerts or "off"}


@router.put("/api/me/alerts")
def put_alerts(body: AlertsBody, request: Request, user: User = Depends(require_user),
               session: Session = Depends(_db)):
    _require_json_header(request)
    u = session.get(User, user.id)
    if u.alerts != body.frequency and body.frequency != "off":
        u.alerts_sent_at = datetime.utcnow()  # the first alert covers jobs from now on, not the whole backlog
    u.alerts = body.frequency
    u.lang = "nl" if body.lang == "nl" else "en"
    session.commit()
    return {"frequency": u.alerts}


@router.get("/alerts/unsubscribe", include_in_schema=False)
@router.post("/alerts/unsubscribe", include_in_schema=False)  # RFC 8058 one-click, sent by mail clients
def alerts_unsubscribe(u: int, t: str, session: Session = Depends(_db)):
    from radar import alerts

    ok = alerts.unsubscribe(session, u, t)
    msg = ("You won't get job alerts any more. You can turn them back on under Account settings." if ok
           else "This unsubscribe link is not valid. You can turn alerts off under Account settings.")
    nl = ("Je krijgt geen vacature-alerts meer. Je kunt ze weer aanzetten onder Accountinstellingen." if ok
          else "Deze afmeldlink is niet geldig. Je kunt alerts uitzetten onder Accountinstellingen.")
    html = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><meta name="robots" content="noindex"><title>'
            f'{escape(settings.site_name)}</title><link rel="stylesheet" href="/static/app.css?v=1"></head>'
            f'<body><main class="wrap max-w-xl pt-[12vh]">'
            f'<div class="card"><h2>{"Unsubscribed" if ok else "Link not valid"}</h2><p>{escape(msg)}</p>'
            f'<p class="muted">{escape(nl)}</p>'
            f'<p><a class="btn primary" href="/#account">{escape(settings.site_name)}</a>'
            f"</p></div></main></body></html>")
    return Response(html, media_type="text/html", status_code=200 if ok else 400)


@router.get("/api/me/export")
def export(user: User = Depends(require_user), session: Session = Depends(_db)):
    """Everything stored about this account, as one JSON file (GDPR data portability)."""
    row = session.get(UserData, user.id)
    body = {"email": user.email, "created_at": user.created_at.isoformat(),
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "profile": row.profile if row else {}, "saved_job_ids": row.saved if row else [],
            "job_alerts": user.alerts or "off"}
    return Response(content=json.dumps(body, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="tech-jobs-radar-data.json"'})


@router.delete("/api/me")
def delete_account(request: Request, response: Response, user: User = Depends(require_user),
                   session: Session = Depends(_db)):
    """Remove the account and everything attached to it (GDPR right to erasure)."""
    _require_json_header(request)
    session.execute(delete(UserData).where(UserData.user_id == user.id))
    session.execute(delete(UserSession).where(UserSession.user_id == user.id))
    session.execute(delete(LoginToken).where(LoginToken.email == user.email))
    session.execute(delete(User).where(User.id == user.id))
    session.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


def cleanup(session: Session) -> dict:
    """Housekeeping after every crawl: expired sessions, login links older than two days (with the IP address
    they were requested from) and accounts unused for INACTIVE_DAYS."""
    now = datetime.utcnow()
    s = session.execute(delete(UserSession).where(UserSession.expires_at < now)).rowcount
    t = session.execute(delete(LoginToken).where(LoginToken.created_at < now - timedelta(days=2))).rowcount
    cutoff = now - timedelta(days=INACTIVE_DAYS)
    stale = list(session.scalars(select(User.id).where(func.coalesce(User.last_login_at, User.created_at) < cutoff)))
    if stale:
        session.execute(delete(UserData).where(UserData.user_id.in_(stale)))
        session.execute(delete(UserSession).where(UserSession.user_id.in_(stale)))
        session.execute(delete(User).where(User.id.in_(stale)))
    session.commit()
    return {"sessions_removed": s, "tokens_removed": t, "accounts_removed": len(stale)}
