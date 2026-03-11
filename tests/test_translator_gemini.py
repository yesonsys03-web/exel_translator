from __future__ import annotations

import io
from email.message import Message
import pytest
from urllib.error import HTTPError

from harmony_translate.translator_gemini import GeminiClient


def test_list_models_filters_to_gemini_generate_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-2.0-flash",
        base_url="https://generativelanguage.googleapis.com",
    )

    def fake_request_json(method: str, path: str, body=None):
        del method, body
        assert path == "/v1beta/models"
        return {
            "models": [
                {
                    "name": "models/gemini-2.0-flash",
                    "displayName": "Gemini 2.0 Flash",
                    "supportedGenerationMethods": ["generateContent"],
                    "inputTokenLimit": 1048576,
                    "outputTokenLimit": 8192,
                },
                {
                    "name": "models/embedding-001",
                    "displayName": "Embedding",
                    "supportedGenerationMethods": ["embedContent"],
                    "inputTokenLimit": 2048,
                    "outputTokenLimit": 0,
                },
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)
    models = client.list_models()

    assert len(models) == 1
    assert models[0].model_id == "gemini-2.0-flash"
    assert models[0].input_token_limit == 1048576


def test_translate_batch_uses_generate_content_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-2.0-flash",
        base_url="https://generativelanguage.googleapis.com",
    )

    def fake_request_json(method: str, path: str, body=None):
        del method, body
        assert path == "/v1beta/models/gemini-2.0-flash:generateContent"
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "안녕하세요"}],
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)
    translated = client.translate_batch(["Hello"], source_lang="EN", target_lang="KO")

    assert translated == ["안녕하세요"]


def test_request_json_retries_on_429_with_retry_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com",
    )

    calls = {"count": 0}
    slept: list[float] = []

    def fake_once(method: str, path: str, body=None):
        del method, path, body
        calls["count"] += 1
        if calls["count"] == 1:
            detail = (
                '{"error":{"details":['
                '{"@type":"type.googleapis.com/google.rpc.RetryInfo","retryDelay":"4s"}'
                "]}}"
            )
            raise HTTPError(
                url="https://example.test",
                code=429,
                msg="RESOURCE_EXHAUSTED",
                hdrs=Message(),
                fp=io.BytesIO(detail.encode("utf-8")),
            )
        return {"ok": True}

    monkeypatch.setattr(client, "_request_json_once", fake_once)
    monkeypatch.setattr("harmony_translate.translator_gemini.time.sleep", slept.append)

    payload = client._request_json("GET", "/v1beta/models")

    assert payload == {"ok": True}
    assert calls["count"] == 2
    assert slept == [4.0]


def test_extract_retry_delay_seconds_from_message_fallback() -> None:
    detail = "Please retry in 4.921498276s."
    assert GeminiClient._extract_retry_delay_seconds(detail) == pytest.approx(
        4.921498276
    )
