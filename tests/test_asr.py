"""录音上传：稳定错误码、限流与并发释放；所有上游调用和告警均 mock。"""
import base64
import threading
from collections import defaultdict, deque
from unittest.mock import Mock

import pytest
import requests
from flask.testing import FlaskClient

import backend.asr as asr


@pytest.fixture(autouse=True)
def upstream(monkeypatch):
    post = Mock(return_value=Mock(
        status_code=200, json=Mock(return_value={"result": {"text": " hello "}})))
    monkeypatch.setattr(asr.requests, "post", post)
    monkeypatch.setattr(asr, "_notify_failure", Mock())
    monkeypatch.setattr(asr, "cf_api_token", Mock(return_value="test-token"))
    monkeypatch.setattr(asr, "_requests", defaultdict(deque))
    monkeypatch.setattr(asr, "_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(asr, "CONFIG", {"asr_rate_limit_per_hour": 120})
    return post


def upload(client, audio=b"a" * 500):
    return client.post("/api/asr", data=audio, content_type="audio/wav")


def assert_error(response, status, code):
    assert response.status_code == status
    assert response.get_json()["code"] == code
    assert response.get_json()["error"]


def assert_slot_released():
    assert asr._slots.acquire(blocking=False)
    asr._slots.release()


@pytest.mark.parametrize("size", [0, 1, 499])
def test_short_audio(client, upstream, size):
    assert_error(upload(client, b"a" * size), 400, "no-speech")
    upstream.assert_not_called()
    asr.cf_api_token.assert_not_called()
    assert not asr._requests


def test_audio_too_long(client, upstream):
    assert_error(upload(client, b"a" * (asr._MAX_AUDIO_BYTES + 1)), 413, "audio-too-long")
    upstream.assert_not_called()
    assert not asr._requests


@pytest.mark.parametrize("size", [500, asr._MAX_AUDIO_BYTES])
def test_success_and_size_boundaries(client, upstream, size):
    audio = b"a" * size
    response = upload(client, audio)
    assert response.status_code == 200
    assert response.get_json()["text"] == "hello"
    assert "user" in response.get_json()
    upstream.assert_called_once_with(
        f"https://api.cloudflare.com/client/v4/accounts/{asr.CF_ACCOUNT_ID}/ai/run/{asr.ASR_MODEL}",
        headers={"Authorization": "Bearer test-token"},
        json={"audio": base64.b64encode(audio).decode()}, timeout=25)
    assert_slot_released()


def test_unconfigured(client, upstream):
    asr.cf_api_token.return_value = ""
    assert_error(upload(client), 503, "service-unavailable")
    upstream.assert_not_called()
    assert not asr._requests


def test_user_rate_limit(client, upstream, monkeypatch):
    monkeypatch.setitem(asr.CONFIG, "asr_rate_limit_per_hour", 1)
    assert upload(client).status_code == 200
    assert_error(upload(client), 429, "rate-limited")
    upstream.assert_called_once()
    assert_slot_released()


def test_rate_limit_is_per_user_and_expires(client, app, upstream, monkeypatch):
    monkeypatch.setitem(asr.CONFIG, "asr_rate_limit_per_hour", 1)
    monkeypatch.setattr(asr.time, "monotonic", lambda: 10000)
    assert upload(client).status_code == 200
    other = app.test_client()
    other.get("/api/auth/me")
    assert upload(other).status_code == 200
    assert_error(upload(client), 429, "rate-limited")
    monkeypatch.setattr(asr.time, "monotonic", lambda: 13600)
    assert upload(client).status_code == 200
    assert upstream.call_count == 3


def test_concurrency_full(client, upstream):
    assert asr._slots.acquire(blocking=False)
    try:
        assert_error(upload(client), 429, "service-busy")
        upstream.assert_not_called()
        # 拒绝请求不能释放其他请求占用的 slot。
        assert not asr._slots.acquire(blocking=False)
    finally:
        asr._slots.release()
    assert upload(client).status_code == 200


@pytest.mark.parametrize("status, expected_status, code", [
    (429, 429, "service-busy"),
    (400, 502, "asr-failed"),
    (401, 502, "asr-failed"),
    (500, 502, "asr-failed"),
    (503, 502, "asr-failed"),
])
def test_upstream_http_error_without_json(client, upstream, status, expected_status, code):
    upstream.return_value = Mock(status_code=status, text="upstream error",
                                 json=Mock(side_effect=ValueError("not JSON")))
    assert_error(upload(client), expected_status, code)
    upstream.return_value.json.assert_not_called()
    asr._notify_failure.assert_called_once()
    assert_slot_released()


@pytest.mark.parametrize("exception, status, code", [
    (requests.Timeout("slow"), 504, "asr-timeout"),
    (requests.ConnectTimeout("slow connect"), 504, "asr-timeout"),
    (requests.ReadTimeout("slow read"), 504, "asr-timeout"),
    (requests.ConnectionError("offline"), 502, "asr-failed"),
    (RuntimeError("unexpected"), 502, "asr-failed"),
])
def test_request_exception(client, upstream, exception, status, code):
    upstream.side_effect = exception
    assert_error(upload(client), status, code)
    asr._notify_failure.assert_called_once()
    assert_slot_released()


@pytest.mark.parametrize("payload", [None, [], {"result": {"text": 123}},
                                     {"success": False, "errors": [{"message": "failed"}]}])
def test_invalid_or_failed_upstream_payload(client, upstream, payload):
    upstream.return_value.json.return_value = payload
    assert_error(upload(client), 502, "asr-failed")
    assert_slot_released()


def test_invalid_json(client, upstream):
    upstream.return_value.json.side_effect = ValueError("not JSON")
    assert_error(upload(client), 502, "asr-failed")
    assert_slot_released()


def test_empty_transcript_still_succeeds(client, upstream):
    upstream.return_value.json.return_value = {"result": {"text": "  "}}
    response = upload(client)
    assert response.status_code == 200
    assert response.get_json()["text"] == ""


def test_csrf_and_origin_protection_unchanged(app, client, upstream):
    raw_client = FlaskClient(app)
    response = upload(raw_client)
    assert response.status_code == 403
    response = client.post("/api/asr", data=b"a" * 500,
                           headers={"Origin": "https://untrusted.invalid"})
    assert response.status_code == 403
    upstream.assert_not_called()
