"""Password hashing with scrypt (Python's standard library): slow and memory-hard, so a stolen hash is expensive
to guess, with a random salt per password so equal passwords never share a hash.

Stored as "scrypt$n$r$p$salt$hash" so the cost can be raised later without breaking existing hashes."""

from __future__ import annotations

import hashlib
import hmac
import secrets

N, R, P = 2**14, 8, 1  # ~16 MB and ~50 ms per hash
MIN_LENGTH = 10
MAX_LENGTH = 128


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=128 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${N}${R}${P}${salt.hex()}${_derive(password, salt, N, R, P).hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        algo, n, r, p, salt, digest = (stored or "").split("$")
        if algo != "scrypt":
            return False
        return hmac.compare_digest(_derive(password, bytes.fromhex(salt), int(n), int(r), int(p)).hex(), digest)
    except (ValueError, TypeError):
        return False


# Checked when the e-mail address is unknown or has no password, so a failed login takes as long either way and
# the response time does not reveal which addresses have accounts.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def problem(password: str) -> str | None:
    """Why a new password is not acceptable, or None."""
    if len(password) < MIN_LENGTH:
        return f"use at least {MIN_LENGTH} characters"
    if len(password) > MAX_LENGTH:
        return f"use at most {MAX_LENGTH} characters"
    if len(set(password)) < 4:
        return "use more different characters"
    return None
