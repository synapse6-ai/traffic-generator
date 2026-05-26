"""AWS S3 CRUD via awslabs.aws-api-mcp-server ``call_aws`` tool."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from aws_credentials import AwsCredentials

MCP_CONNECT_TIMEOUT_SEC = 20.0
MCP_CALL_TIMEOUT_SEC = 15.0


class McpS3Error(Exception):
    """Raised when an MCP S3 operation fails."""


@dataclass
class S3OperationResult:
    command: str
    response: dict[str, Any] | None = None
    data: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def format_copy_source(bucket: str, source_key: str) -> str:
    """URL-encode the key portion for ``aws s3api copy-object --copy-source``."""
    return f"{bucket}/{quote(source_key, safe='/')}"


def _region_flag(region: str) -> str:
    return f"--region {shlex.quote(region)}"


def build_head_bucket_command(bucket: str, region: str) -> str:
    return f"aws s3api head-bucket --bucket {shlex.quote(bucket)} {_region_flag(region)}"


def build_list_buckets_command(region: str) -> str:
    return f"aws s3api list-buckets {_region_flag(region)}"


def build_list_objects_command(
    bucket: str,
    region: str,
    *,
    prefix: str = "",
    max_keys: int = 100,
) -> str:
    cmd = (
        f"aws s3api list-objects-v2 --bucket {shlex.quote(bucket)} "
        f"--max-keys {int(max_keys)} {_region_flag(region)}"
    )
    if prefix:
        cmd += f" --prefix {shlex.quote(prefix)}"
    return cmd


def build_put_object_command(
    bucket: str,
    key: str,
    body_path: Path | str,
    region: str,
    *,
    content_type: str = "text/plain",
) -> str:
    return (
        f"aws s3api put-object --bucket {shlex.quote(bucket)} "
        f"--key {shlex.quote(key)} --body {shlex.quote(str(body_path))} "
        f"--content-type {shlex.quote(content_type)} {_region_flag(region)}"
    )


def build_get_object_command(bucket: str, key: str, out_path: Path | str, region: str) -> str:
    return (
        f"aws s3api get-object --bucket {shlex.quote(bucket)} "
        f"--key {shlex.quote(key)} {shlex.quote(str(out_path))} {_region_flag(region)}"
    )


def build_head_object_command(bucket: str, key: str, region: str) -> str:
    return (
        f"aws s3api head-object --bucket {shlex.quote(bucket)} "
        f"--key {shlex.quote(key)} {_region_flag(region)}"
    )


def build_copy_object_command(bucket: str, source_key: str, dest_key: str, region: str) -> str:
    copy_source = format_copy_source(bucket, source_key)
    return (
        f"aws s3api copy-object --bucket {shlex.quote(bucket)} "
        f"--copy-source {shlex.quote(copy_source)} "
        f"--key {shlex.quote(dest_key)} {_region_flag(region)}"
    )


def build_delete_object_command(bucket: str, key: str, region: str) -> str:
    return (
        f"aws s3api delete-object --bucket {shlex.quote(bucket)} "
        f"--key {shlex.quote(key)} {_region_flag(region)}"
    )


def extract_call_aws_payload(result: Any) -> list[dict[str, Any]]:
    if getattr(result, "structuredContent", None):
        payload = result.structuredContent
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    return []


def unwrap_aws_data(response: Any) -> Any | None:
    """Extract the AWS API JSON payload from an MCP ``call_aws`` wrapper."""
    if response is None:
        return None
    if isinstance(response, str):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return response
    if not isinstance(response, dict):
        return response

    inner = response.get("response")
    if isinstance(inner, dict):
        raw_json = inner.get("json") or inner.get("as_json")
        if raw_json:
            try:
                return json.loads(raw_json)
            except (json.JSONDecodeError, TypeError):
                return raw_json
    return response


def parse_call_aws_row(cli_command: str, row: dict[str, Any]) -> S3OperationResult:
    error = row.get("error")
    if error:
        return S3OperationResult(command=cli_command, error=str(error))

    raw_response = row.get("response")
    if isinstance(raw_response, dict):
        inner = raw_response.get("response")
        if isinstance(inner, dict) and inner.get("error"):
            return S3OperationResult(
                command=cli_command,
                error=str(inner["error"]),
                response=raw_response,
            )

    data = unwrap_aws_data(raw_response)
    response_dict = raw_response if isinstance(raw_response, dict) else {"raw": raw_response}
    return S3OperationResult(command=cli_command, response=response_dict, data=data)


class AwsMcpS3Client:
    """Thin wrapper around AWS API MCP server for S3 object CRUD."""

    def __init__(
        self,
        credentials: AwsCredentials,
        *,
        read_only: bool = False,
        region: str | None = None,
        workdir: Path | None = None,
        call_timeout_sec: float = MCP_CALL_TIMEOUT_SEC,
    ) -> None:
        self.credentials = credentials
        self.read_only = read_only
        self.region = region or credentials.region
        self._workdir = workdir or self._default_workdir()
        self._call_timeout_sec = call_timeout_sec
        self._session: ClientSession | None = None
        self._transport = None

    @staticmethod
    def _default_workdir() -> Path:
        path = Path(os.environ.get("TMPDIR", "/tmp")) / "aws-api-mcp" / "workdir"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _server_env(self) -> dict[str, str]:
        env = self.credentials.to_env()
        env["READ_OPERATIONS_ONLY"] = "true" if self.read_only else "false"
        env["AWS_API_MCP_TELEMETRY"] = "false"
        env["AWS_API_MCP_WORKING_DIR"] = str(self._workdir)
        return env

    def _write_temp_file(self, body: str, *, suffix: str = ".txt") -> Path:
        name = f"mcp-s3-{uuid.uuid4().hex}{suffix}"
        path = self._workdir / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    async def __aenter__(self) -> AwsMcpS3Client:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "awslabs.aws_api_mcp_server.server"],
            env=self._server_env(),
        )
        self._transport = stdio_client(params)
        try:
            read, write = await asyncio.wait_for(
                self._transport.__aenter__(),
                timeout=MCP_CONNECT_TIMEOUT_SEC,
            )
        except Exception:
            await self._cleanup_transport(None, None, None)
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
            await self._cleanup_session(None, exc, None)
            await self._cleanup_transport(None, exc, None)
            raise
        return self

    async def _cleanup_session(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            await self._session.__aexit__(exc_type, exc, tb)
            self._session = None

    async def _cleanup_transport(self, exc_type, exc, tb) -> None:
        if self._transport is not None:
            await self._transport.__aexit__(exc_type, exc, tb)
            self._transport = None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._cleanup_session(exc_type, exc, tb)
        await self._cleanup_transport(exc_type, exc, tb)

    async def aclose(self) -> None:
        """Explicit shutdown for notebook interrupt handlers."""
        await self.__aexit__(None, None, None)

    async def call_aws(self, cli_command: str, *, max_results: int | None = None) -> S3OperationResult:
        if self._session is None:
            raise McpS3Error("Client is not connected. Use async with AwsMcpS3Client(...).")

        arguments: dict[str, Any] = {"cli_command": cli_command}
        if max_results is not None:
            arguments["max_results"] = max_results

        try:
            result = await asyncio.wait_for(
                self._session.call_tool("call_aws", arguments=arguments),
                timeout=self._call_timeout_sec,
            )
        except TimeoutError:
            return S3OperationResult(
                command=cli_command,
                error=f"MCP call timed out after {self._call_timeout_sec:.0f}s",
            )

        rows = extract_call_aws_payload(result)
        if not rows:
            return S3OperationResult(command=cli_command, error="Empty MCP response")
        return parse_call_aws_row(cli_command, rows[0])

    async def head_bucket(self, bucket: str) -> S3OperationResult:
        return await self.call_aws(build_head_bucket_command(bucket, self.region))

    async def list_buckets(self) -> S3OperationResult:
        return await self.call_aws(build_list_buckets_command(self.region))

    async def list_objects(
        self,
        bucket: str,
        *,
        prefix: str = "",
        max_keys: int = 100,
    ) -> S3OperationResult:
        return await self.call_aws(
            build_list_objects_command(bucket, self.region, prefix=prefix, max_keys=max_keys)
        )

    async def put_object(
        self,
        bucket: str,
        key: str,
        body: str,
        *,
        content_type: str = "text/plain",
    ) -> S3OperationResult:
        payload_path = self._write_temp_file(body)
        try:
            cmd = build_put_object_command(
                bucket, key, payload_path, self.region, content_type=content_type
            )
            return await self.call_aws(cmd)
        finally:
            payload_path.unlink(missing_ok=True)

    async def get_object(self, bucket: str, key: str) -> S3OperationResult:
        out_path = self._workdir / f"mcp-s3-get-{uuid.uuid4().hex}.bin"
        try:
            result = await self.call_aws(
                build_get_object_command(bucket, key, out_path, self.region)
            )
            if result.ok and out_path.exists():
                preview = out_path.read_bytes()[:500].decode("utf-8", errors="replace")
                result.data = {**(result.data or {}), "BodyPreview": preview}
            return result
        finally:
            out_path.unlink(missing_ok=True)

    async def head_object(self, bucket: str, key: str) -> S3OperationResult:
        return await self.call_aws(build_head_object_command(bucket, key, self.region))

    async def copy_object(
        self,
        bucket: str,
        source_key: str,
        dest_key: str,
    ) -> S3OperationResult:
        return await self.call_aws(
            build_copy_object_command(bucket, source_key, dest_key, self.region)
        )

    async def delete_object(self, bucket: str, key: str) -> S3OperationResult:
        return await self.call_aws(build_delete_object_command(bucket, key, self.region))
