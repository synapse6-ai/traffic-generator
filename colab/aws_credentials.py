"""Resolve AWS credentials from Colab secrets or environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

AWS_ACCESS_KEY_ID = "AWS_ACCESS_KEY_ID"
AWS_SECRET_ACCESS_KEY = "AWS_SECRET_ACCESS_KEY"
AWS_REGION = "AWS_REGION"
AWS_SESSION_TOKEN = "AWS_SESSION_TOKEN"
DEFAULT_REGION = "us-east-1"


class CredentialError(Exception):
    """Raised when AWS credentials cannot be resolved."""


@dataclass(frozen=True)
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    region: str
    session_token: str | None = None

    def to_env(self) -> dict[str, str]:
        env = {
            AWS_ACCESS_KEY_ID: self.access_key_id,
            AWS_SECRET_ACCESS_KEY: self.secret_access_key,
            AWS_REGION: self.region,
            "AWS_DEFAULT_REGION": self.region,
        }
        if self.session_token:
            env[AWS_SESSION_TOKEN] = self.session_token
        return env


def _colab_secret(name: str) -> str | None:
    try:
        from google.colab import userdata
    except ImportError:
        return None
    try:
        value = userdata.get(name)
    except Exception as exc:
        if type(exc).__name__ in ("SecretNotFoundError", "UserDataArgumentError"):
            return None
        raise RuntimeError(f"Colab secret {name!r}: {exc}") from exc
    return value.strip() if value else None


def lookup_env(name: str) -> str | None:
    """Colab secret first, then environment variable."""
    value = _colab_secret(name) or os.getenv(name)
    return value.strip() if value else None


def resolve_aws_credentials() -> AwsCredentials:
    """Load AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY from Colab secrets or env."""
    access_key_id = lookup_env(AWS_ACCESS_KEY_ID)
    secret_access_key = lookup_env(AWS_SECRET_ACCESS_KEY)
    region = lookup_env(AWS_REGION) or DEFAULT_REGION
    session_token = lookup_env(AWS_SESSION_TOKEN)

    if not access_key_id or not secret_access_key:
        raise CredentialError(
            "Set Colab secrets (or environment variables):\n"
            f"  • {AWS_ACCESS_KEY_ID}\n"
            f"  • {AWS_SECRET_ACCESS_KEY}\n"
            f"Optional: {AWS_REGION} (default {DEFAULT_REGION}), {AWS_SESSION_TOKEN}"
        )

    return AwsCredentials(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        region=region,
        session_token=session_token,
    )


def mask_access_key(access_key_id: str) -> str:
    if len(access_key_id) <= 8:
        return "***"
    return f"{access_key_id[:4]}...{access_key_id[-4:]}"
