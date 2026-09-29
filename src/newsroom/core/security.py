import hashlib
import hmac
import secrets
from functools import cache

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    """Return ``(valid, upgraded_hash)``. Runs a full hash even when no hash exists."""
    if password_hash is None:
        _hasher.verify(password, _dummy_hash())
        return False, None
    return _hasher.verify_and_update(password, password_hash)


@cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def new_csrf_token(secret: str) -> str:
    nonce = secrets.token_urlsafe(24)
    return f"{nonce}.{_sign(secret, nonce)}"


def csrf_token_is_valid(secret: str, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, _, signature = token.partition(".")
    return hmac.compare_digest(signature, _sign(secret, nonce))
