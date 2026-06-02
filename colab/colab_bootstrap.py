"""Find or download colab helper modules; reuse MCP sessions across notebook cells."""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

MODULE_NAMES = (
    "aws_credentials.py",
    "mcp_s3_client.py",
    "guardrail_mcp_client.py",
    "colab_bootstrap.py",
)
DEFAULT_RAW_BASE = "https://raw.githubusercontent.com/synapse6-ai/traffic-generator/main/colab"
DOWNLOAD_DIR = Path("/content/colab-modules")

_aws_mcp: Any = None
_gs_mcp: Any = None


def raw_base() -> str:
    return os.getenv("COLAB_HELPERS_RAW_BASE", DEFAULT_RAW_BASE).rstrip("/")


def find_module_dir() -> Path | None:
    candidates = [
        Path.cwd(),
        Path.cwd() / "colab",
        DOWNLOAD_DIR,
        Path("/content/traffic-generator/colab"),
    ]
    for parent in [Path.cwd(), *Path.cwd().parents]:
        colab = parent / "colab"
        if (colab / "colab_bootstrap.py").exists():
            candidates.append(colab)
    seen: set[Path] = set()
    for directory in candidates:
        resolved = directory.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if all((resolved / name).exists() for name in MODULE_NAMES):
            return resolved
    return None


def download_modules(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    base = raw_base()
    for name in MODULE_NAMES:
        dest = target / name
        url = f"{base}/{name}"
        print(f"  download {url}")
        urllib.request.urlretrieve(url, dest)


def ensure_module_dir() -> Path:
    """Local checkout first; otherwise download all modules to DOWNLOAD_DIR."""
    found = find_module_dir()
    if found is not None:
        return found
    download_modules(DOWNLOAD_DIR)
    if not all((DOWNLOAD_DIR / name).exists() for name in MODULE_NAMES):
        raise RuntimeError(f"Failed to download helpers to {DOWNLOAD_DIR}")
    return DOWNLOAD_DIR


def load_modules() -> Path:
    """Put helpers on sys.path. Call once from the notebook load cell."""
    module_dir = ensure_module_dir()
    path = str(module_dir)
    if path not in sys.path:
        sys.path.insert(0, path)
    print(f"Using modules from: {module_dir}")
    return module_dir


async def get_aws_mcp(credentials: Any) -> Any:
    """Reuse one AWS MCP stdio session across cells (call close_mcp_sessions when done)."""
    global _aws_mcp
    from mcp_s3_client import AwsMcpS3Client

    if _aws_mcp is None:
        _aws_mcp = AwsMcpS3Client(credentials)
        await _aws_mcp.__aenter__()
    return _aws_mcp


async def get_guardrail_mcp(credentials: Any) -> Any:
    global _gs_mcp
    from guardrail_mcp_client import GuardrailMcpClient

    if _gs_mcp is None:
        _gs_mcp = GuardrailMcpClient(credentials)
        await _gs_mcp.__aenter__()
    return _gs_mcp


async def close_mcp_sessions() -> None:
    global _aws_mcp, _gs_mcp
    if _aws_mcp is not None:
        await _aws_mcp.aclose()
        _aws_mcp = None
    if _gs_mcp is not None:
        await _gs_mcp.__aexit__(None, None, None)
        _gs_mcp = None
