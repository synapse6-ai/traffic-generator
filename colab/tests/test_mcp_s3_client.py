from __future__ import annotations

import json

from mcp_s3_client import (
    extract_call_aws_payload,
    parse_call_aws_row,
    unwrap_aws_data,
)


class _Block:
    def __init__(self, text: str) -> None:
        self.text = text


class _Result:
    def __init__(self, structured_content=None, content=None) -> None:
        self.structuredContent = structured_content
        self.content = content or []


def test_extract_call_aws_payload_structured_content():
    result = _Result(structured_content={"result": [{"cli_command": "aws s3 ls", "error": None}]})
    rows = extract_call_aws_payload(result)
    assert rows[0]["cli_command"] == "aws s3 ls"


def test_extract_call_aws_payload_text_list():
    payload = [{"cli_command": "aws sts get-caller-identity", "error": "boom"}]
    result = _Result(content=[_Block(json.dumps(payload))])
    rows = extract_call_aws_payload(result)
    assert rows[0]["error"] == "boom"


def test_extract_call_aws_payload_empty():
    assert extract_call_aws_payload(_Result()) == []


def test_unwrap_aws_data_nested_json():
    wrapper = {
        "response": {
            "json": json.dumps({"Buckets": [{"Name": "demo"}]}),
        }
    }
    data = unwrap_aws_data(wrapper)
    assert data["Buckets"][0]["Name"] == "demo"


def test_parse_call_aws_row_success():
    row = {
        "response": {
            "response": {
                "json": json.dumps({"Account": "123"}),
            }
        }
    }
    result = parse_call_aws_row("aws sts get-caller-identity", row)
    assert result.ok
    assert result.data["Account"] == "123"


def test_parse_call_aws_row_top_level_error():
    result = parse_call_aws_row("aws s3 ls", {"error": "denied"})
    assert not result.ok
    assert result.error == "denied"


def test_parse_call_aws_row_service_error():
    row = {"response": {"response": {"error": "NoSuchBucket"}}}
    result = parse_call_aws_row("aws s3api head-bucket --bucket missing", row)
    assert not result.ok
    assert "NoSuchBucket" in result.error
