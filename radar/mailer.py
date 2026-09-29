"""Outgoing e-mail: only the login link.

`console` (the default) logs the message instead of sending it, for a laptop or a test run. `smtp` sends through
any SMTP relay: Amazon SES (email-smtp.eu-west-1.amazonaws.com, port 587), a mail provider, or a local relay.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from radar.config import settings

log = logging.getLogger(__name__)
OUTBOX: list[EmailMessage] = []  # console backend keeps the last messages, for tests and local use


def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    if settings.mail_backend == "smtp":
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls(context=context)
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(msg)
        log.info("mail sent to %s: %s", _mask(to), subject)
        return
    OUTBOX.append(msg)
    del OUTBOX[:-20]
    log.warning("mail (console backend, not sent) to %s: %s\n%s", to, subject, text)


def _mask(address: str) -> str:
    user, _, domain = address.partition("@")
    return f"{user[:2]}***@{domain}"
