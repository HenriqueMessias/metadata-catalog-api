"""Mints a JWT signed by a local, gitignored dev-only keypair -- so you can
exercise POST/PUT/DELETE routes locally (e.g. via Swagger's "Authorize"
button) without a real Cognito User Pool.

The keypair is generated on first use into .devkeys/ (gitignored) and
reused after that. app/core/security.py only accepts tokens from this
keypair when AUTH_ISSUER=dev (the default) -- never in production, where
AUTH_ISSUER points at a real OIDC issuer instead.

Usage:
    python scripts/mint_dev_token.py [--subject dev-user] [--email dev@example.com]

Paste the printed value into Swagger's "Authorize" dialog as:
    Bearer <token>
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEYS_DIR = Path(".devkeys")


def _ensure_keypair() -> bytes:
    KEYS_DIR.mkdir(exist_ok=True)
    private_path = KEYS_DIR / "private.pem"
    public_path = KEYS_DIR / "public.pem"

    if private_path.exists() and public_path.exists():
        return private_path.read_bytes()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    # stderr, not stdout: stdout must carry only the token, so
    # `TOKEN=$(python scripts/mint_dev_token.py)` works cleanly in scripts.
    print(f"Generated a new dev signing keypair in {KEYS_DIR}/ (gitignored).", file=sys.stderr)
    return private_pem


def mint_token(subject: str, email: str, ttl_minutes: int) -> str:
    private_pem = _ensure_keypair()
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": subject,
        "email": email,
        "iss": "dev",
        "iat": now,
        "exp": now + datetime.timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, private_pem, algorithm="RS256")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--subject", default="dev-user", help="JWT 'sub' claim")
    parser.add_argument("--email", default="dev@example.com", help="JWT 'email' claim")
    parser.add_argument("--ttl-minutes", type=int, default=60)
    args = parser.parse_args()

    print(mint_token(args.subject, args.email, args.ttl_minutes))


if __name__ == "__main__":
    main()
