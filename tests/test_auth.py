from __future__ import annotations

import datetime

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import get_settings
from app.core.security import InvalidTokenError, verify_token


def _generate_keypair() -> tuple[bytes, bytes]:
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
    return private_pem, public_pem


@pytest.fixture
def dev_keypair(tmp_path, monkeypatch):
    private_pem, public_pem = _generate_keypair()
    (tmp_path / "private.pem").write_bytes(private_pem)
    (tmp_path / "public.pem").write_bytes(public_pem)

    monkeypatch.setenv("AUTH_DEV_KEYS_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield private_pem
    get_settings.cache_clear()


def _sign(private_pem: bytes, **claim_overrides) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": "dev-user",
        "email": "dev@example.com",
        "iss": "dev",
        "iat": now,
        "exp": now + datetime.timedelta(minutes=5),
    }
    payload.update(claim_overrides)
    return jwt.encode(payload, private_pem, algorithm="RS256")


def test_verify_token_accepts_a_validly_signed_token(dev_keypair):
    principal = verify_token(_sign(dev_keypair))

    assert principal.subject == "dev-user"
    assert principal.email == "dev@example.com"


def test_verify_token_rejects_expired_token(dev_keypair):
    expired = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
    token = _sign(dev_keypair, exp=expired)

    with pytest.raises(InvalidTokenError):
        verify_token(token)


def test_verify_token_rejects_wrong_issuer(dev_keypair):
    token = _sign(dev_keypair, iss="not-dev")

    with pytest.raises(InvalidTokenError):
        verify_token(token)


def test_verify_token_rejects_token_signed_by_a_different_key(dev_keypair):
    other_private_pem, _ = _generate_keypair()
    token = _sign(other_private_pem)

    with pytest.raises(InvalidTokenError):
        verify_token(token)


def test_verify_token_rejects_token_missing_sub_claim(dev_keypair):
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {"email": "dev@example.com", "iss": "dev", "iat": now, "exp": now + datetime.timedelta(minutes=5)}
    token = jwt.encode(payload, dev_keypair, algorithm="RS256")

    with pytest.raises(InvalidTokenError):
        verify_token(token)


def test_verify_token_rejects_garbage_input(dev_keypair):
    with pytest.raises(InvalidTokenError):
        verify_token("not-a-jwt-at-all")


def test_verify_token_without_a_dev_key_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_DEV_KEYS_DIR", str(tmp_path / "does-not-exist"))
    get_settings.cache_clear()
    try:
        with pytest.raises(InvalidTokenError):
            verify_token("whatever")
    finally:
        get_settings.cache_clear()
