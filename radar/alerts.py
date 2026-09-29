"""Job alerts: new postings that match a signed-in user's saved profile, e-mailed daily or weekly.

Opt-in only (Off by default), from the account card. The profile is matched exactly like the site's
"Personalised" view (web/app.js profileParams). A mail goes out only when there is something new, lists at most
MAX_JOBS postings with the best skill matches first, and carries a one-click unsubscribe link and the
List-Unsubscribe headers mail clients show as a button. At most MAX_PER_RUN alert mails go out per run, so login
mails always stay within the mail provider's daily allowance.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from html import escape
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar import mailer, stats
from radar.config import settings

log = logging.getLogger(__name__)

FREQUENCIES = ("off", "daily", "weekly")
MAX_JOBS = 15
MAX_PER_RUN = 90
_WINDOW = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}
_DUE_AFTER = {"daily": timedelta(hours=20), "weekly": timedelta(days=6, hours=20)}


def profile_filters(profile: dict, since: datetime) -> stats.Filters:
    """The saved profile as filters, the same mapping as the site's Personalised view."""

    def csv(key):
        v = profile.get(key) or []
        return ",".join(v) if isinstance(v, list) and v else None

    return stats.Filters(
        role=csv("roles"), seniority=csv("levels"), experience=csv("exp"), degree=csv("degrees"),
        employees=csv("emps"), org_size=csv("sizes"), remote=csv("remote"), city=csv("cities"),
        exclude_companies=csv("exclude"), language=profile.get("language") or None,
        sponsorship=True if profile.get("visa") else None, exclude_agencies=bool(profile.get("agencies")),
        enrollment="open" if profile.get("noenrol") else None, since=since.isoformat(),
    )


def _secret(session: Session) -> bytes:
    """A random key kept in the database, so unsubscribe links cannot be forged or guessed."""
    from radar.models import Meta

    row = session.get(Meta, "alerts_secret")
    if row is None:
        row = Meta(key="alerts_secret", value=secrets.token_hex(32))
        session.add(row)
        session.flush()
    return row.value.encode()


def unsubscribe_token(session: Session, user) -> str:
    return hmac.new(_secret(session), f"unsub:{user.id}:{user.email}".encode(), hashlib.sha256).hexdigest()[:32]


def unsubscribe_url(session: Session, user) -> str:
    return f"{settings.site_url.rstrip('/')}/alerts/unsubscribe?" + urlencode({"u": user.id,
                                                                             "t": unsubscribe_token(session, user)})


def unsubscribe(session: Session, user_id: int, token: str) -> bool:
    from radar.models import User

    user = session.get(User, user_id)
    if user is None or not hmac.compare_digest(token, unsubscribe_token(session, user)):
        return False
    user.alerts = "off"
    session.commit()
    return True


_TEXT = {
    "en": {"subject": "{n} new tech jobs for you", "subject1": "1 new tech job for you",
           "intro": "New since your last alert, matching your profile on {site}:",
           "more": "and {n} more on the site", "profile": "Change your profile or alerts",
           "stop": "Stop these e-mails", "why": "You get this because you turned on job alerts ({f}) on {site}."},
    "nl": {"subject": "{n} nieuwe techvacatures voor jou", "subject1": "1 nieuwe techvacature voor jou",
           "intro": "Nieuw sinds je vorige alert, passend bij je profiel op {site}:",
           "more": "en nog {n} op de site", "profile": "Profiel of alerts aanpassen",
           "stop": "Geen e-mails meer", "why": "Je krijgt dit omdat je vacature-alerts ({f}) hebt aangezet op {site}."},
}
_FREQ_NL = {"daily": "dagelijks", "weekly": "wekelijks"}


def _compose(session: Session, user, jobs: list[stats.Row], total: int) -> tuple[str, str, str, dict]:
    lang = "nl" if user.lang == "nl" else "en"
    t = _TEXT[lang]
    site = settings.site_name
    base = settings.site_url.rstrip("/")
    home = f"{base}/nl/#profile" if lang == "nl" else f"{base}/#profile"
    stop = unsubscribe_url(session, user)
    freq = _FREQ_NL.get(user.alerts, user.alerts) if lang == "nl" else user.alerts
    subject = t["subject1"] if total == 1 else t["subject"].format(n=total)
    lines = [t["intro"].format(site=site), ""]
    for r in jobs:
        where = r.city or ("Remote" if r.remote else "")
        lines += [f"- {r.title} · {r.company}{' · ' + where if where else ''}", f"  {r.url}"]
    if total > len(jobs):
        lines += ["", t["more"].format(n=total - len(jobs)) + f": {home.replace('#profile', '#jobs')}"]
    lines += ["", f"{t['profile']}: {home}", f"{t['stop']}: {stop}", "", t["why"].format(f=freq, site=site)]
    items = "".join(
        f'<li style="margin:0 0 10px"><a href="{escape(r.url)}" style="font-weight:600">{escape(r.title)}</a><br>'
        f'<span style="color:#5f6b7a">{escape(r.company)}{" · " + escape(r.city or "") if r.city else ""}</span></li>'
        for r in jobs)
    jobs_url = escape(home.replace("#profile", "#jobs"))
    more = (f'<p><a href="{jobs_url}">{escape(t["more"].format(n=total - len(jobs)))}</a></p>'
            if total > len(jobs) else "")
    why = escape(t["why"].format(f=freq, site=site))
    html = (f'<div style="font-family:system-ui,sans-serif;font-size:15px;line-height:1.45;color:#1b1f24">'
            f'<p>{escape(t["intro"].format(site=site))}</p><ul style="padding-left:18px">{items}</ul>{more}'
            f'<p style="font-size:13px;color:#5f6b7a"><a href="{escape(home)}">{escape(t["profile"])}</a> · '
            f'<a href="{escape(stop)}">{escape(t["stop"])}</a><br>{why}</p></div>')
    headers = {"List-Unsubscribe": f"<{stop}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return subject, "\n".join(lines), html, headers


def due(user, now: datetime) -> bool:
    if user.alerts not in _DUE_AFTER:
        return False
    return user.alerts_sent_at is None or now - user.alerts_sent_at >= _DUE_AFTER[user.alerts]


def run(session: Session, now: datetime | None = None) -> dict:
    """Send the alerts that are due. Returns counters."""
    from radar.models import User, UserData

    now = now or datetime.utcnow()
    users = [u for u in session.scalars(select(User).where(User.alerts.in_(("daily", "weekly")))) if due(u, now)]
    if not users:
        return {"due": 0, "sent": 0, "empty": 0}
    rows = stats.CACHE.rows(session)
    sent = empty = failed = 0
    for user in users:
        if sent >= MAX_PER_RUN:
            break
        data = session.get(UserData, user.id)
        profile = (data.profile if data else None) or {}
        since = max(user.alerts_sent_at or now - _WINDOW[user.alerts], now - _WINDOW[user.alerts])
        matched = profile_filters(profile, since).apply(rows)
        have = set(profile.get("skills") or [])
        matched.sort(key=lambda r: (stats.match_score(r, have) if have else 0, r.posted_at or r.first_seen),
                     reverse=True)
        if not matched:
            empty += 1
            user.alerts_sent_at = now
            continue
        subject, text, html, headers = _compose(session, user, matched[:MAX_JOBS], len(matched))
        try:
            mailer.send(user.email, subject, text, html, headers=headers)
        except Exception as e:  # one refused address must not stop the others
            failed += 1
            log.error("alert to %s not sent: %s", mailer._mask(user.email), e)
            continue
        user.alerts_sent_at = now
        sent += 1
    session.commit()
    log.info("alerts: due=%d sent=%d empty=%d failed=%d", len(users), sent, empty, failed)
    return {"due": len(users), "sent": sent, "empty": empty, "failed": failed}
