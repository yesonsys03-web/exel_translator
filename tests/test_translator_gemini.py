from __future__ import annotations

import io
from email.message import Message
import pytest
from urllib.error import HTTPError

from harmony_translate.translator_gemini import (
    GeminiClient,
    GeminiError,
    GeminiModelInfo,
)


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


def test_list_models_excludes_non_text_generation_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com",
    )

    def fake_request_json(method: str, path: str, body=None):
        del method, body
        assert path == "/v1beta/models"
        return {
            "models": [
                {
                    "name": "models/gemini-2.5-flash-preview-tts",
                    "displayName": "Gemini 2.5 Flash TTS",
                    "supportedGenerationMethods": ["generateContent"],
                    "inputTokenLimit": 8192,
                    "outputTokenLimit": 16384,
                },
                {
                    "name": "models/gemini-2.5-flash",
                    "displayName": "Gemini 2.5 Flash",
                    "supportedGenerationMethods": ["generateContent"],
                    "inputTokenLimit": 1048576,
                    "outputTokenLimit": 65536,
                },
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)
    models = client.list_models()

    assert [model.model_id for model in models] == ["gemini-2.5-flash"]


def test_list_models_excludes_pro_models_for_free_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com",
    )

    def fake_request_json(method: str, path: str, body=None):
        del method, body
        assert path == "/v1beta/models"
        return {
            "models": [
                {
                    "name": "models/gemini-3.1-pro-preview",
                    "displayName": "Gemini 3.1 Pro",
                    "supportedGenerationMethods": ["generateContent"],
                    "inputTokenLimit": 1048576,
                    "outputTokenLimit": 65536,
                },
                {
                    "name": "models/gemini-2.5-flash",
                    "displayName": "Gemini 2.5 Flash",
                    "supportedGenerationMethods": ["generateContent"],
                    "inputTokenLimit": 1048576,
                    "outputTokenLimit": 65536,
                },
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)
    models = client.list_models()

    assert [model.model_id for model in models] == ["gemini-2.5-flash"]


def test_translate_batch_uses_generate_content_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-2.0-flash",
        base_url="https://generativelanguage.googleapis.com",
    )

    monkeypatch.setattr(
        client,
        "list_models",
        lambda: [
            GeminiModelInfo(
                model_id="gemini-2.0-flash",
                display_name="Gemini 2.0 Flash",
                input_token_limit=1048576,
                output_token_limit=8192,
            )
        ],
    )

    def fake_request_json(method: str, path: str, body=None):
        assert method == "POST"
        assert path == "/v1beta/models/gemini-2.0-flash:generateContent"
        assert body is not None
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"translations": ["안녕하세요"]}'}],
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)
    translated = client.translate_batch(["Hello"], source_lang="EN", target_lang="KO")

    assert translated == ["안녕하세요"]


def test_translate_batch_batches_multiple_texts_into_single_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-2.0-flash",
        base_url="https://generativelanguage.googleapis.com",
    )

    monkeypatch.setattr(
        client,
        "list_models",
        lambda: [
            GeminiModelInfo(
                model_id="gemini-2.0-flash",
                display_name="Gemini 2.0 Flash",
                input_token_limit=1048576,
                output_token_limit=8192,
            )
        ],
    )

    calls: list[dict[str, object] | None] = []

    def fake_request_json(method: str, path: str, body=None):
        assert method == "POST"
        assert path == "/v1beta/models/gemini-2.0-flash:generateContent"
        calls.append(body)
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"translations": ["하나", "둘", "셋"]}'}],
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    translated = client.translate_batch(
        ["one", "two", "three"],
        source_lang="EN",
        target_lang="KO",
    )

    assert translated == ["하나", "둘", "셋"]
    assert len(calls) == 1


def test_parse_translations_payload_handles_code_fence() -> None:
    response_text = '```json\n{"translations": ["가", "나"]}\n```'

    parsed = GeminiClient._parse_translations_payload(response_text)

    assert parsed == ["가", "나"]


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


def test_match_requested_model_resolves_alias_to_preview_variant() -> None:
    models = [
        GeminiModelInfo(
            model_id="gemini-3-flash-preview",
            display_name="Gemini 3 Flash Preview",
            input_token_limit=1048576,
            output_token_limit=65536,
        ),
        GeminiModelInfo(
            model_id="gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
            input_token_limit=1048576,
            output_token_limit=65536,
        ),
    ]

    resolved = GeminiClient._match_requested_model("gemini-3-flash", models)

    assert resolved == "gemini-3-flash-preview"


def test_translate_batch_uses_resolved_model_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com",
    )

    monkeypatch.setattr(
        client,
        "list_models",
        lambda: [
            GeminiModelInfo(
                model_id="gemini-3-flash-preview",
                display_name="Gemini 3 Flash Preview",
                input_token_limit=1048576,
                output_token_limit=65536,
            )
        ],
    )

    calls: list[str] = []

    def fake_request_json(method: str, path: str, body=None):
        del method, body
        calls.append(path)
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"translations": ["안녕하세요"]}'}],
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    translated = client.translate_batch(["Hello"], source_lang="EN", target_lang="KO")

    assert translated == ["안녕하세요"]
    assert calls == ["/v1beta/models/gemini-3-flash-preview:generateContent"]


def test_translate_batch_retries_with_refreshed_model_after_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com",
    )
    client._resolved_model = "gemini-3-flash"

    list_models_calls = {"count": 0}

    def fake_list_models() -> list[GeminiModelInfo]:
        list_models_calls["count"] += 1
        return [
            GeminiModelInfo(
                model_id="gemini-3-flash-preview",
                display_name="Gemini 3 Flash Preview",
                input_token_limit=1048576,
                output_token_limit=65536,
            )
        ]

    calls: list[str] = []

    def fake_request_json(method: str, path: str, body=None):
        del method, body
        calls.append(path)
        if path == "/v1beta/models/gemini-3-flash:generateContent":
            raise GeminiError(
                'Gemini request failed: 404 {"error":{"message":"models/gemini-3-flash is not found for API version v1beta, or is not supported for generateContent."}}'
            )
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"translations": ["안녕하세요"]}'}],
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "list_models", fake_list_models)
    monkeypatch.setattr(client, "_request_json", fake_request_json)

    translated = client.translate_batch(["Hello"], source_lang="EN", target_lang="KO")

    assert translated == ["안녕하세요"]
    assert list_models_calls["count"] == 1
    assert calls == [
        "/v1beta/models/gemini-3-flash:generateContent",
        "/v1beta/models/gemini-3-flash-preview:generateContent",
    ]


def test_translate_batch_falls_back_to_alternate_model_on_quota_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com",
    )
    client._resolved_model = "gemini-3-flash-preview"

    monkeypatch.setattr(
        client,
        "list_models",
        lambda: [
            GeminiModelInfo(
                model_id="gemini-3-flash-preview",
                display_name="Gemini 3 Flash Preview",
                input_token_limit=1048576,
                output_token_limit=65536,
            ),
            GeminiModelInfo(
                model_id="gemini-2.5-flash",
                display_name="Gemini 2.5 Flash",
                input_token_limit=1048576,
                output_token_limit=65536,
            ),
        ],
    )

    calls: list[str] = []

    def fake_request_json(method: str, path: str, body=None):
        del method, body
        calls.append(path)
        if path == "/v1beta/models/gemini-3-flash-preview:generateContent":
            raise GeminiError(
                'Gemini request failed: 429 {"error":{"message":"Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3-flash","details":[{"@type":"type.googleapis.com/google.rpc.QuotaFailure","violations":[{"quotaDimensions":{"model":"gemini-3-flash"}}]}]}}'
            )
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"translations": ["안녕하세요"]}'}],
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    translated = client.translate_batch(["Hello"], source_lang="EN", target_lang="KO")

    assert translated == ["안녕하세요"]
    assert calls == [
        "/v1beta/models/gemini-3-flash-preview:generateContent",
        "/v1beta/models/gemini-2.5-flash:generateContent",
    ]


def test_translate_batch_keeps_rotating_until_available_model_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com",
    )
    client._resolved_model = "gemini-3-flash-preview"

    monkeypatch.setattr(
        client,
        "list_models",
        lambda: [
            GeminiModelInfo(
                model_id="gemini-3-flash-preview",
                display_name="Gemini 3 Flash Preview",
                input_token_limit=1048576,
                output_token_limit=65536,
            ),
            GeminiModelInfo(
                model_id="gemini-2.5-flash",
                display_name="Gemini 2.5 Flash",
                input_token_limit=1048576,
                output_token_limit=65536,
            ),
            GeminiModelInfo(
                model_id="gemini-2.0-flash",
                display_name="Gemini 2.0 Flash",
                input_token_limit=1048576,
                output_token_limit=8192,
            ),
        ],
    )

    calls: list[str] = []
    quota_error = (
        'Gemini request failed: 429 {"error":{"message":"Quota exceeded for metric: '
        'generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3-flash",'
        '"details":[{"@type":"type.googleapis.com/google.rpc.QuotaFailure","violations":[{"quotaDimensions":{"model":"gemini-3-flash"}}]}]}}'
    )

    def fake_request_json(method: str, path: str, body=None):
        del method, body
        calls.append(path)
        if path in {
            "/v1beta/models/gemini-3-flash-preview:generateContent",
            "/v1beta/models/gemini-2.5-flash:generateContent",
        }:
            raise GeminiError(quota_error)
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"translations": ["안녕하세요"]}'}],
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    translated = client.translate_batch(["Hello"], source_lang="EN", target_lang="KO")

    assert translated == ["안녕하세요"]
    assert calls[0] == "/v1beta/models/gemini-3-flash-preview:generateContent"
    assert calls[-1] == "/v1beta/models/gemini-2.0-flash:generateContent"
    assert len(set(calls)) == len(calls)
    assert len(calls) >= 2


def test_translate_batch_falls_back_after_invalid_text_modality_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com",
    )
    client._resolved_model = "gemini-2.5-flash-preview-tts"

    monkeypatch.setattr(
        client,
        "list_models",
        lambda: [
            GeminiModelInfo(
                model_id="gemini-2.5-flash-preview-tts",
                display_name="Gemini 2.5 Flash TTS",
                input_token_limit=8192,
                output_token_limit=16384,
            ),
            GeminiModelInfo(
                model_id="gemini-2.5-flash",
                display_name="Gemini 2.5 Flash",
                input_token_limit=1048576,
                output_token_limit=65536,
            ),
        ],
    )

    calls: list[str] = []

    def fake_request_json(method: str, path: str, body=None):
        del method, body
        calls.append(path)
        if path == "/v1beta/models/gemini-2.5-flash-preview-tts:generateContent":
            raise GeminiError(
                'Gemini request failed: 400 {"error":{"message":"The requested combination of response modalities (TEXT) is not supported by the model. models/gemini-2.5-flash-preview-tts accepts the following combination of response modalities:\n* AUDIO\n"}}'
            )
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": '{"translations": ["안녕하세요"]}'}],
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    translated = client.translate_batch(["Hello"], source_lang="EN", target_lang="KO")

    assert translated == ["안녕하세요"]
    assert calls == [
        "/v1beta/models/gemini-2.5-flash-preview-tts:generateContent",
        "/v1beta/models/gemini-2.5-flash:generateContent",
    ]


def test_alternate_ranking_prefers_flash_over_pro_after_quota_issue() -> None:
    models = [
        GeminiModelInfo(
            model_id="gemini-3.1-pro-preview",
            display_name="Gemini 3.1 Pro",
            input_token_limit=1048576,
            output_token_limit=65536,
        ),
        GeminiModelInfo(
            model_id="gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
            input_token_limit=1048576,
            output_token_limit=65536,
        ),
        GeminiModelInfo(
            model_id="gemini-2.0-flash-lite",
            display_name="Gemini 2.0 Flash Lite",
            input_token_limit=1048576,
            output_token_limit=8192,
        ),
    ]

    ranked = GeminiClient._rank_candidate_models(
        "gemini-3.1-pro",
        models,
        prefer_low_quota_risk=True,
    )

    assert ranked[0].model_id == "gemini-2.0-flash-lite"
    assert ranked[1].model_id == "gemini-2.5-flash"


def test_quota_exhausted_model_gets_temporary_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3.1-pro",
        base_url="https://generativelanguage.googleapis.com",
    )
    monkeypatch.setattr("harmony_translate.translator_gemini.time.time", lambda: 100.0)
    exc = GeminiError(
        'Gemini request failed: 429 {"error":{"details":[{"retryDelay":"28s"}]}}'
    )

    client._mark_model_temporarily_unavailable("gemini-3.1-pro-preview", exc)

    assert client._is_model_temporarily_unavailable("gemini-3.1-pro-preview") is True


def test_resolve_generation_model_skips_cooldown_blocked_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com",
    )
    client._resolved_model = "gemini-3-flash-preview"

    models = [
        GeminiModelInfo(
            model_id="gemini-3-flash-preview",
            display_name="Gemini 3 Flash Preview",
            input_token_limit=1048576,
            output_token_limit=65536,
        ),
        GeminiModelInfo(
            model_id="gemini-2.5-flash",
            display_name="Gemini 2.5 Flash",
            input_token_limit=1048576,
            output_token_limit=65536,
        ),
    ]
    monkeypatch.setattr(client, "list_models", lambda: models)
    monkeypatch.setattr(
        client,
        "_is_model_temporarily_unavailable",
        lambda model_id: model_id == "gemini-3-flash-preview",
    )

    resolved = client._resolve_generation_model()

    assert resolved == "gemini-2.5-flash"


def test_second_request_skips_previously_quota_blocked_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = GeminiClient(
        api_key="gemini-key",
        model="gemini-3-flash",
        base_url="https://generativelanguage.googleapis.com",
    )

    monkeypatch.setattr(
        client,
        "list_models",
        lambda: [
            GeminiModelInfo(
                model_id="gemini-3-flash-preview",
                display_name="Gemini 3 Flash Preview",
                input_token_limit=1048576,
                output_token_limit=65536,
            ),
            GeminiModelInfo(
                model_id="gemini-2.5-flash",
                display_name="Gemini 2.5 Flash",
                input_token_limit=1048576,
                output_token_limit=65536,
            ),
        ],
    )

    monkeypatch.setattr("harmony_translate.translator_gemini.time.time", lambda: 100.0)

    calls: list[str] = []
    quota_error = GeminiError(
        'Gemini request failed: 429 {"error":{"message":"Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3-flash","details":[{"retryDelay":"26s"}]}}'
    )

    def fake_request_json(method: str, path: str, body=None):
        del method, body
        calls.append(path)
        if path == "/v1beta/models/gemini-3-flash-preview:generateContent":
            raise quota_error
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": '{"translations": ["안녕하세요", "안녕하세요"]}'}
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    translated = client.translate_batch(
        ["Hello", "World"], source_lang="EN", target_lang="KO"
    )

    assert translated == ["안녕하세요", "안녕하세요"]
    assert calls == [
        "/v1beta/models/gemini-3-flash-preview:generateContent",
        "/v1beta/models/gemini-2.5-flash:generateContent",
    ]
