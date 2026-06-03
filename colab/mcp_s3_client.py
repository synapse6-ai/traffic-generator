"""S3 upload/list via awslabs.aws-api-mcp-server ``call_aws`` tool."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, TextIO

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from aws_credentials import AwsCredentials

MCP_CONNECT_TIMEOUT_SEC = 30.0
MCP_CALL_TIMEOUT_SEC = 120.0


def _running_in_notebook() -> bool:
    try:
        get_ipython  # type: ignore[name-defined]
    except NameError:
        return False
    return True


_colab_stream_patch_applied = False


def _patch_colab_outstream_fileno() -> None:
    """ipykernel OutStream raises UnsupportedOperation on fileno(); MCP spawn needs it."""
    global _colab_stream_patch_applied
    if _colab_stream_patch_applied or not _running_in_notebook():
        return
    try:
        import io

        from ipykernel.iostream import OutStream
    except ImportError:
        return

    devnull_fd = os.open(os.devnull, os.O_WRONLY)

    def _fileno(self: Any) -> int:
        copy = getattr(self, "_original_stdstream_copy", None)
        if copy is not None:
            return copy
        return os.dup(devnull_fd)

    OutStream.fileno = _fileno  # type: ignore[method-assign]
    _colab_stream_patch_applied = True


class _StreamFilenoProxy:
    """Give subprocess a real fileno; keep Colab display on the original stream."""

    def __init__(self, display: Any, backing: TextIO) -> None:
        self._display = display
        self._backing = backing

    def fileno(self) -> int:
        return self._backing.fileno()

    def write(self, data: str) -> int:
        return self._display.write(data)

    def flush(self) -> None:
        self._display.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._display, name)


@contextlib.contextmanager
def _real_stdio_for_mcp() -> Iterator[None]:
    """Colab/Jupyter OutStream has no fileno(); MCP subprocess creation needs one."""
    if not _running_in_notebook():
        yield
        return

    _patch_colab_outstream_fileno()
    saved_out, saved_err = sys.stdout, sys.stderr
    out_back = open(os.devnull, "w")
    err_back = open(os.devnull, "w")
    try:
        sys.stdout = _StreamFilenoProxy(saved_out, out_back)
        sys.stderr = _StreamFilenoProxy(saved_err, err_back)
        yield
    finally:
        sys.stdout = saved_out
        sys.stderr = saved_err
        out_back.close()
        err_back.close()


def _notebook_errlog() -> TextIO:
    return open(os.devnull, "w")


def run_notebook_async(coro):  # noqa: ANN001
    """Run an async coroutine from a Colab cell (nested event loop + stream fileno)."""
    import nest_asyncio

    _patch_colab_outstream_fileno()
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    with _real_stdio_for_mcp():
        return loop.run_until_complete(coro)


def _mcp_stdio_client(params: StdioServerParameters, *, errlog: TextIO | None = None):
    """Notebook-safe stdio transport (real stderr file, never Colab OutStream)."""
    if errlog is not None:
        return stdio_client(params, errlog=errlog)
    if _running_in_notebook():
        return stdio_client(params, errlog=_notebook_errlog())
    return stdio_client(params)


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


def _region_flag(region: str) -> str:
    return f"--region {shlex.quote(region)}"


def build_head_bucket_command(bucket: str, region: str) -> str:
    return f"aws s3api head-bucket --bucket {shlex.quote(bucket)} {_region_flag(region)}"


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
    """Thin wrapper around AWS API MCP server for S3 head/list/put."""

    def __init__(
        self,
        credentials: AwsCredentials,
        *,
        region: str | None = None,
        workdir: Path | None = None,
        call_timeout_sec: float = MCP_CALL_TIMEOUT_SEC,
    ) -> None:
        self.credentials = credentials
        self.region = region or credentials.region
        self._workdir = workdir or self._default_workdir()
        self._call_timeout_sec = call_timeout_sec
        self._session: ClientSession | None = None
        self._transport = None
        self._errlog: TextIO | None = None

    @staticmethod
    def _default_workdir() -> Path:
        path = Path(os.environ.get("TMPDIR", "/tmp")) / "aws-api-mcp" / "workdir"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _server_env(self) -> dict[str, str]:
        env = self.credentials.to_env()
        env["READ_OPERATIONS_ONLY"] = "false"
        env["AWS_API_MCP_TELEMETRY"] = "false"
        env["AWS_API_MCP_WORKING_DIR"] = str(self._workdir)
        env["AWS_API_MCP_ALLOW_UNRESTRICTED_LOCAL_FILE_ACCESS"] = "unrestricted"
        return env

    async def __aenter__(self) -> AwsMcpS3Client:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "awslabs.aws_api_mcp_server.server"],
            env=self._server_env(),
        )
        with _real_stdio_for_mcp():
            if _running_in_notebook():
                self._errlog = _notebook_errlog()
                self._transport = _mcp_stdio_client(params, errlog=self._errlog)
            else:
                self._transport = _mcp_stdio_client(params)
            try:
                read, write = await asyncio.wait_for(
                    self._transport.__aenter__(),
                    timeout=MCP_CONNECT_TIMEOUT_SEC,
                )
            except Exception:
                await self._cleanup_transport(None, None, None)
                self._close_errlog()
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
                self._close_errlog()
                raise
        return self

    def _close_errlog(self) -> None:
        if self._errlog is not None:
            try:
                self._errlog.close()
            except OSError:
                pass
            self._errlog = None

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
        self._close_errlog()

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

    async def put_object_file(
        self,
        bucket: str,
        key: str,
        file_path: Path | str,
        *,
        content_type: str = "application/octet-stream",
    ) -> S3OperationResult:
        """Upload a local file via ``aws s3api put-object`` (no temp copy)."""
        path = Path(file_path)
        if not path.is_file():
            return S3OperationResult(
                command=f"put-object {bucket}/{key}",
                error=f"File not found: {path}",
            )
        cmd = build_put_object_command(
            bucket, key, path, self.region, content_type=content_type
        )
        return await self.call_aws(cmd)
