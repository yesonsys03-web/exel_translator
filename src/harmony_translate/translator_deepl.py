from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib import request, error


class DeepLError(RuntimeError):
    pass


@dataclass
class DeepLUsage:
    character_count: int
    character_limit: int


class DeepLClient:
    # [ANCHOR:DEEPL_CLIENT]
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def usage(self) -> DeepLUsage:
        # [ANCHOR:DEEPL_USAGE_REQUEST]
        payload = self._request_json("GET", "/v2/usage")
        character_count = payload.get("character_count", 0)
        character_limit = payload.get("character_limit", 0)
        return DeepLUsage(
            character_count=int(character_count),
            character_limit=int(character_limit),
        )

    def translate_batch(
        self,
        texts: list[str],
        *,
        source_lang: str,
        target_lang: str,
        glossary_id: str | None = None,
    ) -> list[str]:
        # [ANCHOR:DEEPL_TRANSLATE_BATCH]
        if not texts:
            return []
        try:
            return self._translate_batch_once(
                texts,
                source_lang=source_lang,
                target_lang=target_lang,
                glossary_id=glossary_id,
            )
        except DeepLError as exc:
            if len(texts) <= 1 or not self._is_payload_too_large_error(exc):
                raise

        midpoint = len(texts) // 2
        left = self.translate_batch(
            texts[:midpoint],
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_id=glossary_id,
        )
        right = self.translate_batch(
            texts[midpoint:],
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_id=glossary_id,
        )
        return [*left, *right]

    def _translate_batch_once(
        self,
        texts: list[str],
        *,
        source_lang: str,
        target_lang: str,
        glossary_id: str | None,
    ) -> list[str]:
        body: dict[str, object] = {
            "text": texts,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }
        if glossary_id:
            body["glossary_id"] = glossary_id
        payload = self._request_json("POST", "/v2/translate", body)
        raw_translations = payload.get("translations", [])
        if not isinstance(raw_translations, list):
            raise DeepLError("DeepL response missing translations list")

        translated_texts: list[str] = []
        for item in raw_translations:
            if not isinstance(item, dict) or "text" not in item:
                raise DeepLError("DeepL response contains malformed translation entry")
            translated_texts.append(str(item["text"]))
        return translated_texts

    @staticmethod
    def _is_payload_too_large_error(exc: DeepLError) -> bool:
        message = str(exc)
        return " 413 " in message or "Payload too large" in message

    def _request_json(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = request.Request(
            url=f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"DeepL-Auth-Key {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise DeepLError("DeepL response payload is not an object")
                return payload
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise DeepLError(f"DeepL request failed: {exc.code} {detail}") from exc
        except error.URLError as exc:
            raise DeepLError(f"DeepL request failed: {exc.reason}") from exc
