from __future__ import annotations

import asyncio
from collections import deque

from traffic_generator import (
    KEY_PREFIXES,
    MAX_RECENT_KEYS,
    execute_operation,
    pick_operation,
    random_key,
)


class _OkResult:
    ok = True
    error = None


class _Client:
    async def put_object(self, bucket, key, body, *, content_type="text/plain"):
        return _OkResult()

    async def list_objects(self, bucket, *, prefix="", max_keys=100):
        return _OkResult()

    async def get_object(self, bucket, key):
        return _OkResult()

    async def head_object(self, bucket, key):
        return _OkResult()

    async def copy_object(self, bucket, source_key, dest_key):
        return _OkResult()

    async def delete_object(self, bucket, key):
        return _OkResult()


def test_pick_operation_empty_keys():
    assert pick_operation(deque()) == "PutObject"


def test_execute_put_updates_recent_keys():
    recent = deque(maxlen=MAX_RECENT_KEYS)
    op, result = asyncio.run(
        execute_operation(_Client(), "demo-bucket", "PutObject", recent)
    )
    assert op == "PutObject"
    assert result.ok
    assert len(recent) == 1


def test_execute_delete_removes_key():
    recent = deque(["public/traffic-abc.txt"], maxlen=MAX_RECENT_KEYS)
    op, result = asyncio.run(
        execute_operation(_Client(), "demo-bucket", "DeleteObject", recent)
    )
    assert op == "DeleteObject"
    assert result.ok
    assert len(recent) == 0


def test_random_key_uses_mandate_prefixes():
    keys = {random_key() for _ in range(20)}
    assert all(any(key.startswith(prefix) for prefix in KEY_PREFIXES) for key in keys)
