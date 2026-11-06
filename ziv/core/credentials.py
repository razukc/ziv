"""ziv.core.credentials — secrets at rest and in comparison.

Keys and tokens are stored as SHA-256 hashes and compared in constant time.
The plaintext exists exactly once: in the response that mints it.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

ENROLL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def secret_matches(secret: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), stored_hash)


def new_token(nbytes: int = 32) -> str:
    """A bearer token or device key: url-safe, 43 characters for 32 bytes."""
    return secrets.token_urlsafe(nbytes)


def new_enroll_code(length: int = 8) -> str:
    return "".join(secrets.choice(ENROLL_ALPHABET) for _ in range(length))


def new_id(prefix: str, nbytes: int = 6) -> str:
    return f"{prefix}_{secrets.token_hex(nbytes)}"


def new_utterance_id(now: float, seq: int = 0) -> str:
    """Time-ordered and unique: 13 digits of epoch milliseconds, a 6-digit
    per-process sequence so ids minted in the same millisecond sort in order,
    then 8 random url-safe characters against collisions across processes."""
    return f"{int(now * 1000):013d}{seq % 1_000_000:06d}{secrets.token_urlsafe(6)}"
