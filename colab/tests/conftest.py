"""Load notebook library cell into legacy module names for pytest."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

_COLAB_DIR = Path(__file__).resolve().parent.parent
_NOTEBOOK = _COLAB_DIR / "s3_traffic_generator_mcp_colab.ipynb"

_AWS_NAMES = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "AWS_SESSION_TOKEN",
    "DEFAULT_REGION",
    "CredentialError",
    "AwsCredentials",
    "resolve_aws_credentials",
    "mask_access_key",
}

_MCP_NAMES = {
    "MCP_CONNECT_TIMEOUT_SEC",
    "MCP_CALL_TIMEOUT_SEC",
    "McpS3Error",
    "S3OperationResult",
    "format_copy_source",
    "build_head_bucket_command",
    "build_list_buckets_command",
    "build_list_objects_command",
    "build_put_object_command",
    "build_get_object_command",
    "build_head_object_command",
    "build_copy_object_command",
    "build_delete_object_command",
    "extract_call_aws_payload",
    "unwrap_aws_data",
    "parse_call_aws_row",
    "AwsMcpS3Client",
}

_TRAFFIC_NAMES = {
    "KEY_PREFIXES_ALLOWED",
    "KEY_PREFIXES_DENIED",
    "KEY_PREFIXES",
    "KEY_SUFFIXES",
    "OPERATIONS",
    "OPERATION_WEIGHTS",
    "MAX_RECENT_KEYS",
    "MAX_CONSECUTIVE_ERRORS",
    "ERROR_BACKOFF_CAP_SEC",
    "TrafficStats",
    "random_key",
    "pick_operation",
    "error_backoff_sec",
    "verify_access",
    "execute_operation",
    "mcp_client",
    "run_traffic_loop",
}


def _library_source() -> str:
    nb = json.loads(_NOTEBOOK.read_text())
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        src = "".join(cell["source"])
        if "class AwsCredentials" in src and "class AwsMcpS3Client" in src:
            return src
    raise RuntimeError(f"Library cell not found in {_NOTEBOOK}")


def _module(name: str, keys: set[str], namespace: dict) -> types.ModuleType:
    mod = types.ModuleType(name)
    for key in keys:
        if key in namespace:
            setattr(mod, key, namespace[key])
    return mod


_namespace: dict = {}
exec(compile(_library_source(), str(_NOTEBOOK), "exec"), _namespace)  # noqa: S102
sys.modules["aws_credentials"] = _module("aws_credentials", _AWS_NAMES, _namespace)
sys.modules["mcp_s3_client"] = _module("mcp_s3_client", _MCP_NAMES, _namespace)
sys.modules["traffic_generator"] = _module("traffic_generator", _TRAFFIC_NAMES, _namespace)
