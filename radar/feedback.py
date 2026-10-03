"""The feedback page: visitors report a bug, a wrong or missing listing, or make a suggestion.

Each message is stored and e-mailed to the site owner (RADAR_ALERT_EMAIL) with the sender as Reply-To when they
left an address. A hidden field catches bots, and each visitor can send a few messages an hour. Messages are
deleted after a year.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from radar.analytics import client_ip
from radar.auth import _EMAIL, _db, _require_json_header
from radar.config import settings
from radar.models import Feedback

router = APIRouter()
KEEP_DAYS = 365
MAX_PER_HOUR = 5
_hits: dict[str, deque] = {}
_lock = threading.Lock()
_KINDS = {"bug": "Something does not work", "listing": "Wrong or missing listing", "idea": "Suggestion",
          "other": "Other"}


class FeedbackIn(BaseModel):
    kind: Literal["bug", "listing", "idea", "other"] = "other"
    message: str = Field(max_length=4000)
    email: str | None = Field(default=None, max_length=200)
    page: str | None = Field(default=None, max_length=300)
    lang: str = "en"
    website: str | None = None  # hidden in the form: only bots fill it in


def _allowed(ip: str) -> bool:
    now = time.monotonic()
    with _lock:
        q = _hits.setdefault(ip, deque())
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= MAX_PER_HOUR:
            return False
        q.append(now)
        return True


@router.post("/api/feedback")
def submit(body: FeedbackIn, request: Request, session: Session = Depends(_db)):
    _require_json_header(request)
    if body.website:
        return {"ok": True}  # a bot: pretend it worked
    message = body.message.strip()
    if len(message) < 5:
        raise HTTPException(422, "please write a few words")
    email = (body.email or "").strip().lower() or None
    if email and not _EMAIL.match(email):
        raise HTTPException(422, "that does not look like an e-mail address")
    if not _allowed(client_ip(request) or "unknown"):
        raise HTTPException(429, "too many messages; try again in an hour")
    page = (body.page or "").strip()[:300] or None
    lang = "nl" if body.lang == "nl" else "en"
    session.add(Feedback(created_at=datetime.utcnow(), kind=body.kind, message=message, email=email, page=page,
                         lang=lang))
    session.commit()
    if settings.alert_email:
        from radar import mailer

        text = (f"{_KINDS[body.kind]}\n\n{message}\n\n"
                f"From: {email or 'no e-mail address given'}\nPage: {page or '-'}\nLanguage: {lang}")
        try:
            mailer.send(settings.alert_email, f"[{settings.site_name}] Feedback: {_KINDS[body.kind]}", text,
                        headers={"Reply-To": email} if email else None)
        except Exception:  # the message is stored either way
            import logging

            logging.getLogger(__name__).exception("feedback e-mail could not be sent")
    return {"ok": True}


def cleanup(session: Session) -> int:
    """Delete feedback older than KEEP_DAYS (as the privacy statement says)."""
    n = session.execute(delete(Feedback).where(Feedback.created_at < datetime.utcnow() - timedelta(days=KEEP_DAYS)))
    session.commit()
    return n.rowcount
