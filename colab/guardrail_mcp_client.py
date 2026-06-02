"""GuardrailStudio InstantEvidence MCP gateway client (streamable HTTP)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from aws_credentials import lookup_env

GUARDRAILSTUDIO_MCP_URL = "GUARDRAILSTUDIO_MCP_URL"
GUARDRAILSTUDIO_MCP_TOKEN = "GUARDRAILSTUDIO_MCP_TOKEN"

MCP_CONNECT_TIMEOUT_SEC = 30.0
MCP_CALL_TIMEOUT_SEC = 300.0
MCP_HTTP_READ_TIMEOUT_SEC = 300.0
MCP_HTTP_CONNECT_TIMEOUT_SEC = 15.0


class GuardrailCredentialError(Exception):
    """Raised when GuardrailStudio MCP credentials cannot be resolved."""


class GuardrailMcpError(Exception):
    """Raised when an MCP tool call fails."""


@dataclass(frozen=True)
class GuardrailMcpCredentials:
    url: str
    token: str

    def auth_headers(self) -> dict[str, str]:
        token = self.token.strip()
        if not token.lower().startswith("bearer "):
            token = f"Bearer {token}"
        return {"Authorization": token}


def resolve_guardrail_credentials() -> GuardrailMcpCredentials:
    """Load MCP URL and API key from Colab secrets or environment."""
    url = lookup_env(GUARDRAILSTUDIO_MCP_URL)
    token = lookup_env(GUARDRAILSTUDIO_MCP_TOKEN)
    if not url or not token:
        raise GuardrailCredentialError(
            "Set Colab secrets (or environment variables):\n"
            f"  • {GUARDRAILSTUDIO_MCP_URL} — e.g. https://mcp-dev.instantevidence.ai/v1/mcp\n"
            f"  • {GUARDRAILSTUDIO_MCP_TOKEN} — your gks_live_* API key"
        )
    return GuardrailMcpCredentials(url=url.rstrip("/"), token=token)


def mask_token(token: str) -> str:
    raw = token.removeprefix("Bearer ").removeprefix("bearer ").strip()
    if raw.startswith("gks_live_") and len(raw) > 16:
        return f"gks_live_{raw[9:13]}...{raw[-4:]}"
    if len(raw) <= 8:
        return "***"
    return f"{raw[:4]}...{raw[-4:]}"


def extract_tool_payload(result: Any) -> Any:
    """Prefer structuredContent; fall back to text content blocks."""
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured

    texts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            texts.append(text)
    if not texts:
        return None

    combined = "\n".join(texts)
    try:
        return json.loads(combined)
    except json.JSONDecodeError:
        return combined


class GuardrailMcpClient:
    """HTTP MCP client for GuardrailStudio gateway tools."""

    def __init__(
        self,
        credentials: GuardrailMcpCredentials,
        *,
        call_timeout_sec: float = MCP_CALL_TIMEOUT_SEC,
        read_timeout_sec: float = MCP_HTTP_READ_TIMEOUT_SEC,
        connect_timeout_sec: float = MCP_HTTP_CONNECT_TIMEOUT_SEC,
    ) -> None:
        self.credentials = credentials
        self._call_timeout_sec = call_timeout_sec
        self._read_timeout_sec = read_timeout_sec
        self._connect_timeout_sec = connect_timeout_sec
        self._http_client: httpx.AsyncClient | None = None
        self._transport: Any = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> GuardrailMcpClient:
        headers = self.credentials.auth_headers()
        self._http_client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(
                connect=self._connect_timeout_sec,
                read=self._read_timeout_sec,
                write=30.0,
                pool=15.0,
            ),
        )
        self._transport = streamable_http_client(
            self.credentials.url,
            http_client=self._http_client,
            terminate_on_close=True,
        )
        try:
            read, write, _session_id = await asyncio.wait_for(
                self._transport.__aenter__(),
                timeout=MCP_CONNECT_TIMEOUT_SEC,
            )
        except Exception:
            await self._close_http()
            raise

        self._session = ClientSession(read, write)
        try:
            await asyncio.wait_for(
                self._session.__aenter__(),
                timeout=MCP_CONNECT_TIMEOUT_SEC,
            )
            await asyncio.wait_for(
                self._session.initialize(),
                timeout=MCP_CONNECT_TIMEOUT_SEC,
            )
        except Exception as exc:
            await self._cleanup_session(exc, None)
            await self._cleanup_transport(exc, None)
            await self._close_http()
            raise exc
        return self

    async def _cleanup_session(self, exc_type: Any, exc: Any) -> None:
        if self._session is not None:
            await self._session.__aexit__(exc_type, exc, None)
            self._session = None

    async def _cleanup_transport(self, exc_type: Any, exc: Any) -> None:
        if self._transport is not None:
            await self._transport.__aexit__(exc_type, exc, None)
            self._transport = None

    async def _close_http(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self._cleanup_session(exc_type, exc)
        await self._cleanup_transport(exc_type, exc)
        await self._close_http()

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if self._session is None:
            raise GuardrailMcpError("Client is not connected.")
        args = arguments or {}
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, args),
                timeout=self._call_timeout_sec,
            )
        except TimeoutError as exc:
            raise GuardrailMcpError(
                f"Tool {name!r} timed out after {self._call_timeout_sec:.0f}s"
            ) from exc

        is_error = bool(getattr(result, "isError", False))
        data = extract_tool_payload(result)
        if is_error:
            raise GuardrailMcpError(
                f"Tool {name!r} returned an error: {json.dumps(data, default=str)[:500]}"
            )
        return data

    async def whoami(self) -> dict[str, Any]:
        data = await self.call_tool("auth.whoami", {})
        if not isinstance(data, dict):
            raise GuardrailMcpError(f"Unexpected whoami payload: {data!r}")
        return data

    async def object_metadata_search(
        self,
        *,
        project_id: str | None = None,
        project_name: str | None = None,
        target_id: str | None = None,
        key_prefix: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"limit": limit, "offset": offset}
        if project_id:
            arguments["project_id"] = project_id
        if project_name:
            arguments["project_name"] = project_name
        if target_id:
            arguments["target_id"] = target_id
        if key_prefix:
            arguments["key_prefix"] = key_prefix
        data = await self.call_tool("object.metadata.search", arguments)
        if not isinstance(data, dict):
            raise GuardrailMcpError(f"Unexpected object.metadata.search payload: {data!r}")
        return data

    async def nl_query(
        self,
        question: str,
        *,
        project_name: str | None = None,
    ) -> Any:
        arguments: dict[str, Any] = {"question": question}
        if project_name:
            arguments["project_name"] = project_name
        return await self.call_tool("nl.query", arguments)
