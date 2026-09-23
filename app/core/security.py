"""JWT verification for authenticated write operations.

See docs/sdd-api-authentication.md for the full design. Two modes,
controlled by `Settings.auth_issuer`:

- `"dev"` (the default): verifies tokens signed by a local, gitignored
  keypair (see scripts/mint_dev_token.py). No AWS account needed to run or
  test this locally -- this is what makes the auth layer testable the same
  way as everything else in this project.
- anything else: treated as a real OIDC issuer (e.g. a Cognito User Pool),
  verified against its JWKS endpoint (`Settings.auth_jwks_url`).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel

from app.core.config import get_settings


class Principal(BaseModel):
    """The authenticated caller, derived from a verified JWT's claims."""

    subject: str
    email: str | None = None


class InvalidTokenError(Exception):
    """Raised for any token that fails verification, for any reason."""


def _dev_public_key() -> str:
    path = Path(get_settings().auth_dev_keys_dir) / "public.pem"
    if not path.exists():
        raise InvalidTokenError(
            "No dev signing key found -- run `python scripts/mint_dev_token.py` first "
            "(AUTH_ISSUER=dev is the default; see docs/sdd-api-authentication.md)."
        )
    return path.read_text()


@lru_cache
def _jwk_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url)


def verify_token(token: str) -> Principal:
    """Verifies signature, expiry and issuer/audience; returns the caller.

    Raises InvalidTokenError on any failure -- callers (app/api/deps.py)
    turn that into a 401, never a 500.
    """
    settings = get_settings()
    try:
        if settings.auth_issuer == "dev":
            payload = jwt.decode(
                token,
                _dev_public_key(),
                algorithms=["RS256"],
                issuer="dev",
                options={"verify_aud": False},
            )
        else:
            if not settings.auth_jwks_url:
                raise InvalidTokenError("AUTH_JWKS_URL is not configured for the active AUTH_ISSUER")
            signing_key = _jwk_client(settings.auth_jwks_url).get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.auth_audience,
                issuer=settings.auth_issuer,
            )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    subject = payload.get("sub")
    if not subject:
        raise InvalidTokenError("Token is missing the 'sub' claim")

    return Principal(subject=subject, email=payload.get("email"))
