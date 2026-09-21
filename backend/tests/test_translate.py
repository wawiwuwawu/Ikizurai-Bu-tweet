"""Tes translasi: parser JSON, payload, retry."""
import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.translate import (  # noqa: E402
    SYSTEM_PROMPT, build_messages, parse_batch_json, translate_batch, translate_with_retry,
)

IDS = ["111", "222"]


def test_parse_json_polos():
    content = json.dumps([{"id": "111", "id_text": "satu"}, {"id": "222", "id_text": "dua"}])
    assert parse_batch_json(content, IDS) == {"111": "satu", "222": "dua"}


def test_parse_json_dengan_markdown_fence():
    content = "```json\n" + json.dumps([{"id": "111", "id_text": "satu"}]) + "\n```"
    assert parse_batch_json(content, IDS) == {"111": "satu"}


def test_parse_json_dengan_teks_ekstra():
    content = "Ini terjemahannya:\n" + json.dumps([{"id": "222", "id_text": "dua"}]) + "\nSemoga membantu!"
    assert parse_batch_json(content, IDS) == {"222": "dua"}


def test_parse_json_menolak_id_asing_dan_kosong():
    content = json.dumps([{"id": "999", "id_text": "asing"}, {"id": "111", "id_text": "  "}])
    assert parse_batch_json(content, IDS) == {}


def test_parse_json_rusak():
    assert parse_batch_json("bukan json sama sekali", IDS) == {}
    assert parse_batch_json("", IDS) == {}


def test_build_messages_konten():
    msgs = build_messages([{"id_str": "111", "text": "こんにちは"}])
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == SYSTEM_PROMPT
    assert json.loads(msgs[1]["content"]) == {"id": "111", "text": "こんにちは"}


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_translate_batch_sukses_dan_mengirim_reasoning_effort():
    payload = {"choices": [{"message": {"content": '[{"id":"111","id_text":"halo"}]'}, "finish_reason": "stop"}]}
    s = FakeSession([FakeResp(200, payload)])
    result, err = translate_batch(
        s, base_url="http://x/v1", api_key="k", model="m",
        tweets=[{"id_str": "111", "text": "やあ"}], reasoning_effort="none",
    )
    assert result == {"111": "halo"} and err is None
    assert s.calls[0]["json"]["reasoning_effort"] == "none"
    assert s.calls[0]["headers"]["Authorization"] == "Bearer k"


def test_translate_batch_http_error():
    s = FakeSession([FakeResp(504, {"error": {"code": "RATE_LIMIT_EXECUTION_TIMEOUT"}})])
    result, err = translate_batch(s, base_url="http://x/v1", api_key="k", model="m",
                                  tweets=[{"id_str": "111", "text": "やあ"}])
    assert result == {} and "504" in err


def test_translate_with_retry_berhasil_setelah_gagal():
    payload = {"choices": [{"message": {"content": '[{"id":"111","id_text":"halo"}]'}}]}
    s = FakeSession([FakeResp(504, {"error": {}}), FakeResp(200, payload)])
    slept = []
    result, err = translate_with_retry(s, base_url="http://x/v1", api_key="k", model="m",
                                       tweets=[{"id_str": "111", "text": "やあ"}],
                                       attempts=3, base_delay=1, sleep=slept.append)
    assert result == {"111": "halo"} and err is None
    assert slept == [1]


def test_translate_with_retry_koneksi_error():
    s = FakeSession([requests.ConnectionError("boom"), requests.ConnectionError("boom")])
    result, err = translate_with_retry(s, base_url="http://x/v1", api_key="k", model="m",
                                       tweets=[{"id_str": "111", "text": "やあ"}],
                                       attempts=2, base_delay=1, sleep=lambda *_: None)
    assert result == {} and "koneksi" in err
