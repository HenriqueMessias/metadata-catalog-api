from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Data Catalog Service"
    api_prefix: str = "/api/v1"

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "data_catalog"
    mongo_collection: str = "metadata"

    default_page_size: int = 20
    max_page_size: int = 100

    # "dev" (default) verifies tokens signed by the local dev keypair
    # (see scripts/mint_dev_token.py) -- no AWS account needed to run or
    # test this locally. Point at a real Cognito User Pool's issuer/JWKS
    # in production (see docs/sdd-api-authentication.md).
    auth_issuer: str = "dev"
    auth_audience: str | None = None
    auth_jwks_url: str | None = None
    auth_dev_keys_dir: str = ".devkeys"


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (avoids re-parsing env on every call)."""
    return Settings()
