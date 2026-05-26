from __future__ import annotations

import os

import pytest

from aws_credentials import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    CredentialError,
    mask_access_key,
    resolve_aws_credentials,
)


def test_resolve_from_env(monkeypatch):
    monkeypatch.setenv(AWS_ACCESS_KEY_ID, "AKIAENV")
    monkeypatch.setenv(AWS_SECRET_ACCESS_KEY, "env-secret")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    creds = resolve_aws_credentials()
    assert creds.access_key_id == "AKIAENV"
    assert creds.secret_access_key == "env-secret"
    assert creds.region == "eu-west-1"


def test_resolve_default_region(monkeypatch):
    monkeypatch.setenv(AWS_ACCESS_KEY_ID, "AKIAENV")
    monkeypatch.setenv(AWS_SECRET_ACCESS_KEY, "env-secret")
    monkeypatch.delenv("AWS_REGION", raising=False)
    creds = resolve_aws_credentials()
    assert creds.region == "us-east-1"


def test_resolve_missing_credentials(monkeypatch):
    for key in list(os.environ):
        if key.startswith("AWS_"):
            monkeypatch.delenv(key, raising=False)
    with pytest.raises(CredentialError) as exc:
        resolve_aws_credentials()
    message = str(exc.value)
    assert AWS_ACCESS_KEY_ID in message
    assert AWS_SECRET_ACCESS_KEY in message
    assert "SECRET_REF" not in message


def test_mask_access_key():
    assert mask_access_key("AKIA1234567890") == "AKIA...7890"
