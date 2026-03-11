from __future__ import annotations

import pytest

from harmony_translate.translator_deepl import DeepLClient, DeepLError


def test_translate_batch_splits_and_preserves_order_on_413(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DeepLClient(api_key="test-key", base_url="https://api-free.deepl.com")

    def fake_request_json(
        method: str,
        path: str,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert method == "POST"
        assert path == "/v2/translate"
        assert body is not None
        texts = body.get("text")
        assert isinstance(texts, list)
        if len(texts) > 2:
            raise DeepLError(
                'DeepL request failed: 413 {"message":"Payload too large."}'
            )
        return {
            "translations": [{"text": f"KO:{text}"} for text in texts],
        }

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    translated = client.translate_batch(
        ["one", "two", "three", "four", "five"],
        source_lang="EN",
        target_lang="KO",
    )

    assert translated == ["KO:one", "KO:two", "KO:three", "KO:four", "KO:five"]


def test_translate_batch_raises_on_413_for_single_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DeepLClient(api_key="test-key", base_url="https://api-free.deepl.com")

    def fake_request_json(
        method: str,
        path: str,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        del method, path, body
        raise DeepLError('DeepL request failed: 413 {"message":"Payload too large."}')

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    with pytest.raises(DeepLError, match="413"):
        client.translate_batch(["single"], source_lang="EN", target_lang="KO")
