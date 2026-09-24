import hashlib
import hmac
import secrets

KEY_PREFIX = "tp_"


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    # Keys are high-entropy random strings, so a fast hash is enough (no salt/bcrypt needed).
    return hashlib.sha256(key.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
