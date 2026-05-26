from __future__ import annotations

import shlex

from mcp_s3_client import (
    build_copy_object_command,
    build_delete_object_command,
    build_get_object_command,
    build_head_bucket_command,
    build_head_object_command,
    build_list_objects_command,
    build_put_object_command,
    format_copy_source,
)


def test_format_copy_source_encodes_special_chars():
    assert format_copy_source("my-bucket", "public/a b+c.txt") == "my-bucket/public/a%20b%2Bc.txt"


def test_build_head_bucket_command():
    cmd = build_head_bucket_command("my-bucket", "us-east-1")
    assert cmd == "aws s3api head-bucket --bucket my-bucket --region us-east-1"


def test_build_head_bucket_command_quotes_unsafe_bucket():
    cmd = build_head_bucket_command("my bucket", "us-east-1")
    assert cmd == f"aws s3api head-bucket --bucket {shlex.quote('my bucket')} --region us-east-1"


def test_build_list_objects_command():
    cmd = build_list_objects_command("b", "eu-west-1", prefix="public/", max_keys=25)
    assert "--max-keys 25" in cmd
    assert "--prefix public/" in cmd
    assert "--region eu-west-1" in cmd


def test_build_put_object_command():
    cmd = build_put_object_command("b", "k.txt", "/tmp/payload.txt", "us-east-1")
    assert "put-object" in cmd
    assert "--body /tmp/payload.txt" in cmd
    assert "--region us-east-1" in cmd


def test_build_get_object_command():
    cmd = build_get_object_command("b", "k.txt", "/tmp/out.bin", "ap-southeast-1")
    assert "get-object" in cmd
    assert shlex.quote("/tmp/out.bin") in cmd


def test_build_copy_object_command_encodes_source():
    cmd = build_copy_object_command("b", "public/a b.txt", "public/copy.txt", "us-east-1")
    assert "--copy-source" in cmd
    assert "public/a%20b.txt" in cmd


def test_build_delete_object_command():
    cmd = build_delete_object_command("b", "public/x.txt", "us-east-1")
    assert cmd == "aws s3api delete-object --bucket b --key public/x.txt --region us-east-1"


def test_build_head_object_command():
    cmd = build_head_object_command("b", "data/file.json", "us-east-2")
    assert cmd == "aws s3api head-object --bucket b --key data/file.json --region us-east-2"
