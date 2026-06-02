"""Unit tests for colab helper modules (no MCP servers required)."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aws_credentials import CredentialError, lookup_env, mask_access_key, resolve_aws_credentials
from guardrail_mcp_client import extract_tool_payload, mask_token, resolve_guardrail_credentials
from guardrail_mcp_client import GuardrailCredentialError


def test_mask_access_key() -> None:
    assert mask_access_key("AKIAIOSFODNN7EXAMPLE") == "AKIA...MPLE"


def test_mask_token_gks() -> None:
    token = "gks_live_" + "a" * 32
    masked = mask_token(token)
    assert "..." in masked
    assert token not in masked


def test_lookup_env_prefers_env() -> None:
    with patch.dict(os.environ, {"TEST_COLAB_LOOKUP": "from-env"}, clear=False):
        assert lookup_env("TEST_COLAB_LOOKUP") == "from-env"


def test_resolve_aws_credentials_missing() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with patch("aws_credentials._colab_secret", return_value=None):
            with pytest.raises(CredentialError, match="AWS_ACCESS_KEY_ID"):
                resolve_aws_credentials()


def test_resolve_guardrail_missing() -> None:
    with patch("guardrail_mcp_client.lookup_env", return_value=None):
        with pytest.raises(GuardrailCredentialError):
            resolve_guardrail_credentials()


def test_extract_tool_payload_structured() -> None:
    result = SimpleNamespace(structuredContent={"tenantId": "t1"}, content=[])
    assert extract_tool_payload(result) == {"tenantId": "t1"}


def test_extract_tool_payload_text_json() -> None:
    result = SimpleNamespace(
        structuredContent=None,
        content=[SimpleNamespace(text='{"ok": true}')],
    )
    assert extract_tool_payload(result) == {"ok": True}


def test_find_module_dir_local() -> None:
    from colab_bootstrap import find_module_dir

    root = find_module_dir()
    assert root is not None
    assert (root / "aws_credentials.py").exists()
