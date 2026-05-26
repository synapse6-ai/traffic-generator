"""S3 traffic generator using AWS MCP S3 CRUD operations."""

from __future__ import annotations

import asyncio
import random
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import AsyncIterator

from aws_credentials import AwsCredentials, mask_access_key, resolve_aws_credentials
from mcp_s3_client import AwsMcpS3Client, McpS3Error, S3OperationResult

# Align with apps/api/s3_event_generator_v2.py mandate-relevant key taxonomy.
KEY_PREFIXES_ALLOWED = ("public/", "data/", "uploads/", "archive/")
KEY_PREFIXES_DENIED = ("secret/", "tmp/", "temp/", "staging/")
KEY_PREFIXES = KEY_PREFIXES_ALLOWED + KEY_PREFIXES_DENIED
KEY_SUFFIXES = (".csv", ".json", ".txt", ".log", ".pdf", "")

OPERATIONS = ("PutObject", "GetObject", "HeadObject", "ListObjectsV2", "CopyObject", "DeleteObject")
OPERATION_WEIGHTS = (35, 15, 10, 10, 15, 15)
MAX_RECENT_KEYS = 50
MAX_CONSECUTIVE_ERRORS = 5
ERROR_BACKOFF_CAP_SEC = 8.0


@dataclass
class TrafficStats:
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    operations: dict[str, int] = field(default_factory=lambda: {op: 0 for op in OPERATIONS})
    errors: int = 0
    cycles: int = 0

    def record(self, operation: str, *, ok: bool) -> None:
        self.operations[operation] = self.operations.get(operation, 0) + 1
        if not ok:
            self.errors += 1


def random_key() -> str:
    prefix = random.choice(KEY_PREFIXES)
    suffix = random.choice(KEY_SUFFIXES)
    token = uuid.uuid4().hex[:8]
    return f"{prefix}traffic-{token}{suffix}"


def pick_operation(recent_keys: deque[str]) -> str:
    if not recent_keys:
        return "PutObject"
    return random.choices(OPERATIONS, weights=OPERATION_WEIGHTS, k=1)[0]


def error_backoff_sec(consecutive_errors: int) -> float:
    if consecutive_errors <= 0:
        return 0.0
    return min(2 ** (consecutive_errors - 1), ERROR_BACKOFF_CAP_SEC)


async def verify_access(client: AwsMcpS3Client, bucket: str) -> None:
    identity = await client.call_aws("aws sts get-caller-identity")
    if not identity.ok:
        raise McpS3Error(f"Credential check failed: {identity.error}")

    head = await client.head_bucket(bucket)
    if not head.ok:
        raise McpS3Error(f"Bucket access check failed for {bucket!r}: {head.error}")


async def execute_operation(
    client: AwsMcpS3Client,
    bucket: str,
    operation: str,
    recent_keys: deque[str],
) -> tuple[str, S3OperationResult]:
    if operation == "PutObject":
        key = random_key()
        body = f"colab-traffic {datetime.now(UTC).isoformat()}"
        result = await client.put_object(bucket, key, body)
        if result.ok:
            recent_keys.append(key)
            while len(recent_keys) > MAX_RECENT_KEYS:
                recent_keys.popleft()
        return operation, result

    if operation == "ListObjectsV2":
        prefix = random.choice(KEY_PREFIXES)
        return operation, await client.list_objects(bucket, prefix=prefix)

    if not recent_keys:
        key = random_key()
        body = f"seed {datetime.now(UTC).isoformat()}"
        seed = await client.put_object(bucket, key, body)
        if seed.ok:
            recent_keys.append(key)
        return "PutObject", seed

    key = random.choice(list(recent_keys))

    if operation == "GetObject":
        return operation, await client.get_object(bucket, key)
    if operation == "HeadObject":
        return operation, await client.head_object(bucket, key)
    if operation == "CopyObject":
        dest_key = random_key()
        result = await client.copy_object(bucket, key, dest_key)
        if result.ok:
            recent_keys.append(dest_key)
        return operation, result
    if operation == "DeleteObject":
        result = await client.delete_object(bucket, key)
        if result.ok:
            try:
                recent_keys.remove(key)
            except ValueError:
                pass
        return operation, result

    raise McpS3Error(f"Unsupported operation: {operation}")


async def _run_cycles(
    client: AwsMcpS3Client,
    bucket: str,
    stats: TrafficStats,
    *,
    cycles: int,
    min_interval_sec: float,
    max_interval_sec: float,
    max_consecutive_errors: int,
    recent_keys: deque[str],
) -> None:
    consecutive_errors = 0

    for cycle in range(1, cycles + 1):
        operation = pick_operation(recent_keys)
        op_name, result = await execute_operation(client, bucket, operation, recent_keys)
        stats.record(op_name, ok=result.ok)
        stats.cycles = cycle

        if result.ok:
            consecutive_errors = 0
            status = "OK"
        else:
            consecutive_errors += 1
            status = f"ERR: {result.error}"
            backoff = error_backoff_sec(consecutive_errors)
            if backoff:
                print(f"  backoff {backoff:.0f}s after error")
                await asyncio.sleep(backoff)
            if consecutive_errors >= max_consecutive_errors:
                raise McpS3Error(
                    f"Stopping after {consecutive_errors} consecutive errors. Last: {result.error}"
                )

        print(f"[{cycle}/{cycles}] {op_name} -> {status}")

        if cycle < cycles:
            delay = random.uniform(min_interval_sec, max_interval_sec)
            await asyncio.sleep(delay)


@asynccontextmanager
async def mcp_client(
    credentials: AwsCredentials,
    *,
    read_only: bool = False,
    region: str | None = None,
) -> AsyncIterator[AwsMcpS3Client]:
    client = AwsMcpS3Client(credentials, read_only=read_only, region=region)
    try:
        await client.__aenter__()
        yield client
    finally:
        await client.aclose()


async def run_traffic_loop(
    *,
    bucket: str,
    credentials: AwsCredentials | None = None,
    client: AwsMcpS3Client | None = None,
    cycles: int = 20,
    min_interval_sec: float = 3.0,
    max_interval_sec: float = 12.0,
    read_only: bool = False,
    region: str | None = None,
    max_consecutive_errors: int = MAX_CONSECUTIVE_ERRORS,
    verify: bool = True,
) -> TrafficStats:
    creds = credentials or resolve_aws_credentials()
    stats = TrafficStats()
    recent_keys: deque[str] = deque(maxlen=MAX_RECENT_KEYS)

    print(
        f"Starting MCP S3 traffic generator | bucket={bucket} region={region or creds.region} "
        f"key={mask_access_key(creds.access_key_id)} cycles={cycles} read_only={read_only}"
    )

    if client is not None:
        if verify:
            await verify_access(client, bucket)
            print("Caller identity and bucket access OK")
        await _run_cycles(
            client,
            bucket,
            stats,
            cycles=cycles,
            min_interval_sec=min_interval_sec,
            max_interval_sec=max_interval_sec,
            max_consecutive_errors=max_consecutive_errors,
            recent_keys=recent_keys,
        )
    else:
        async with mcp_client(creds, read_only=read_only, region=region) as managed:
            if verify:
                await verify_access(managed, bucket)
                print("Caller identity and bucket access OK")
            await _run_cycles(
                managed,
                bucket,
                stats,
                cycles=cycles,
                min_interval_sec=min_interval_sec,
                max_interval_sec=max_interval_sec,
                max_consecutive_errors=max_consecutive_errors,
                recent_keys=recent_keys,
            )

    print(
        f"Done. ops={stats.operations} errors={stats.errors} "
        f"elapsed={(datetime.now(UTC) - stats.started_at).total_seconds():.1f}s"
    )
    return stats
