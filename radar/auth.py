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

import hashlib
import json
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from radar import mailer
from radar.config import settings
from radar.models import LoginToken, User, UserData, UserSession

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


@router.post("/api/auth/request")
def request_link(body: LinkRequest, request: Request, session: Session = Depends(_db)):
    _require_json_header(request)
    email = body.email.strip().lower()
    if not _EMAIL.match(email):
        raise HTTPException(422, "that does not look like an e-mail address")
    ip = request.client.host if request.client else "unknown"
    if not _ip_allowed(ip):
        raise HTTPException(429, "too many requests; try again later")
    hour_ago = datetime.utcnow() - timedelta(hours=1)
    recent = session.scalar(select(func.count()).select_from(LoginToken)
                            .where(LoginToken.email == email, LoginToken.created_at >= hour_ago)) or 0
    if recent < MAX_PER_EMAIL_PER_HOUR:
        token = secrets.token_urlsafe(32)
        session.add(LoginToken(token_hash=_hash(token), email=email, ip=ip,
                               expires_at=datetime.utcnow() + timedelta(minutes=TOKEN_MINUTES)))
        session.commit()
        # The link always points at the configured public site, never at the Host header of this request (which
        # a caller controls). Only the console backend, which sends nothing, uses the local address.
        base = str(request.base_url) if settings.mail_backend == "console" else settings.site_url
        _send_link(email, token, "nl" if body.lang == "nl" else "en", base)
    # same answer either way, so the endpoint does not reveal who has an account or who is rate-limited
    return {"ok": True}


def _send_link(email: str, token: str, lang: str, base: str) -> None:
    link = f"{base.rstrip('/')}/auth/verify?token={quote(token)}"
    name = settings.site_name
    if lang == "nl":
        subject = f"Inloggen bij {name}"
        text = (f"Klik op deze link om in te loggen bij {name}:\n\n{link}\n\nDe link werkt één keer en is "
                f"{TOKEN_MINUTES} minuten geldig. Heb je dit niet aangevraagd? Dan kun je deze e-mail negeren.")
    else:
        subject = f"Sign in to {name}"
        text = (f"Click this link to sign in to {name}:\n\n{link}\n\nThe link works once and is valid for "
                f"{TOKEN_MINUTES} minutes. If you did not ask for it, you can ignore this e-mail.")
    html = "<p>" + escape(text.split("\n\n")[0]) + f'</p><p><a href="{escape(link)}">{escape(link)}</a></p><p>' + \
        escape(text.split("\n\n")[2]) + "</p>"
    mailer.send(email, subject, text, html)


@router.get("/auth/verify", include_in_schema=False)
def verify(token: str, request: Request, session: Session = Depends(_db)):
    row = session.scalar(select(LoginToken).where(LoginToken.token_hash == _hash(token)))
    now = datetime.utcnow()
    if row is None or row.used_at is not None or row.expires_at < now:
        return RedirectResponse("/?login=expired#profile", status_code=303)
    row.used_at = now
    user = session.scalar(select(User).where(User.email == row.email))
    if user is None:
        user = User(email=row.email)
        session.add(user)
        session.flush()
    user.last_login_at = now
    raw = secrets.token_urlsafe(32)
    session.add(UserSession(token_hash=_hash(raw), user_id=user.id,
                            expires_at=now + timedelta(days=settings.session_days)))
    session.commit()
    resp = RedirectResponse("/?login=ok#profile", status_code=303)
    # Secure behind a TLS-terminating proxy too (the app then sees http); only a local run gets a plain cookie
    local = request.url.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
    resp.set_cookie(COOKIE, raw, max_age=settings.session_days * 86400, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https" or not local, path="/")
    return resp


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
def me(user: User | None = Depends(current_user)):
    if user is None:
        return {"signed_in": False}
    return {"signed_in": True, "email": user.email, "since": user.created_at.date().isoformat()}


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


@router.get("/api/me/export")
def export(user: User = Depends(require_user), session: Session = Depends(_db)):
    """Everything stored about this account, as one JSON file (GDPR data portability)."""
    row = session.get(UserData, user.id)
    body = {"email": user.email, "created_at": user.created_at.isoformat(),
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "profile": row.profile if row else {}, "saved_job_ids": row.saved if row else []}
    return Response(content=json.dumps(body, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="my-tech-jobs-radar-data.json"'})


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
