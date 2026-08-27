"""Password hashing and opaque auth-token helpers.

- Passwords are hashed with bcrypt (never stored or logged in plaintext).
- Host auth tokens are random opaque strings handed to the client once. Only a
  SHA-256 digest of the token is stored in the database, so a database leak
  does not expose usable tokens (M3 decision D25).
"""

import hashlib
import secrets

import bcrypt

#: bcrypt only uses the first 72 bytes of a password; the API schemas cap the
#: password length at 72 characters to avoid silent truncation.
BCRYPT_MAX_BYTES = 72

#: Length of the raw opaque token generated for a host session.
_RAW_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password`` (safe for a single password)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if ``password`` matches the given bcrypt ``password_hash``."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash (e.g. not bcrypt) must never authenticate.
        return False


def generate_auth_token() -> str:
    """Generate a cryptographically random opaque bearer token."""
    return secrets.token_urlsafe(_RAW_TOKEN_BYTES)


def hash_auth_token(token: str) -> str:
    """Return the hex digest stored in the database for ``token``."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
