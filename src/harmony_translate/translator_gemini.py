# === ANCHOR: TRANSLATOR_GEMINI_START ===
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any
from urllib import error, parse, request


class GeminiError(RuntimeError):
    pass


@dataclass
class GeminiModelInfo:
    model_id: str
    display_name: str
    input_token_limit: int
    output_token_limit: int


class GeminiClient:
    MAX_RETRY_ATTEMPTS = 5
    MAX_BATCH_SIZE = 20
    MAX_BATCH_CHARACTERS = 12000
    NON_TEXT_MODEL_MARKERS = (
        "tts",
        "image",
        "audio",
        "native-audio",
        "computer-use",
        "robotics",
    )

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._resolved_model: str | None = None
        self._temporarily_unavailable_models: dict[str, float] = {}

    def usage(self):
        return None

    def list_models(self) -> list[GeminiModelInfo]:
        payload = self._request_json("GET", "/v1beta/models")
        raw_models = payload.get("models", [])
        if not isinstance(raw_models, list):
            return []

        models: list[GeminiModelInfo] = []
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if not name.startswith("models/gemini"):
                continue
            if not self._supports_text_generation_model(name):
                continue
            generation_methods = item.get("supportedGenerationMethods", [])
            if not isinstance(generation_methods, list):
                continue
            if "generateContent" not in generation_methods:
                continue

            model_id = name.removeprefix("models/")
            display_name = str(item.get("displayName", model_id))
            input_token_limit = int(item.get("inputTokenLimit", 0) or 0)
            output_token_limit = int(item.get("outputTokenLimit", 0) or 0)
            models.append(
                GeminiModelInfo(
                    model_id=model_id,
                    display_name=display_name,
                    input_token_limit=input_token_limit,
                    output_token_limit=output_token_limit,
                )
            )
        models.sort(key=lambda model: model.model_id)
        return models

    def translate_batch(
        self,
        texts: list[str],
        *,
        source_lang: str,
        target_lang: str,
        glossary_id: str | None = None,
    ) -> list[str]:
        del glossary_id
        translated: list[str] = []
        for chunk in self._chunk_texts(texts):
            translated.extend(
                self._translate_chunk(
                    texts=chunk,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )
            )
        return translated

    def _translate_chunk(
        self, *, texts: list[str], source_lang: str, target_lang: str
    ) -> list[str]:
        prompt = (
            "Translate each item in the input list. Return strict JSON with this exact "
            'shape: {"translations": ["..."]}. Do not include markdown fences or extra text. '
            f"Source language: {source_lang}. Target language: {target_lang}. Preserve list order.\n\n"
            "Input JSON:\n" + json.dumps({"texts": texts}, ensure_ascii=False)
        )
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {"temperature": 0},
        }

        attempted_models: set[str] = set()
        model_id = self._resolve_generation_model()
        while True:
            attempted_models.add(model_id)
            try:
                payload = self._request_json(
                    "POST", f"/v1beta/models/{model_id}:generateContent", body
                )
                self._resolved_model = model_id
                break
            except GeminiError as exc:
                if self._is_model_quota_exhausted_error(exc):
                    self._mark_model_temporarily_unavailable(model_id, exc)
                    fallback_model = self._resolve_alternate_generation_model(
                        excluded_models=attempted_models,
                        refresh=True,
                    )
                elif self._is_invalid_text_modality_error(exc):
                    self._mark_model_temporarily_unavailable(model_id, exc)
                    fallback_model = self._resolve_alternate_generation_model(
                        excluded_models=attempted_models,
                        refresh=True,
                    )
                elif self._is_model_not_found_error(exc):
                    fallback_model = self._resolve_generation_model(refresh=True)
                else:
                    raise
                if fallback_model in attempted_models:
                    raise
                model_id = fallback_model

        response_text = self._extract_response_text(payload)
        parsed = self._parse_translations_payload(response_text)
        if len(parsed) != len(texts):
            raise GeminiError("Gemini response translation count mismatch")
        return parsed

    @classmethod
    def _chunk_texts(cls, texts: list[str]) -> list[list[str]]:
        chunks: list[list[str]] = []
        current_chunk: list[str] = []
        current_size = 0
        for text in texts:
            text_size = len(text)
            if current_chunk and (
                len(current_chunk) >= cls.MAX_BATCH_SIZE
                or current_size + text_size > cls.MAX_BATCH_CHARACTERS
            ):
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0
            current_chunk.append(text)
            current_size += text_size
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    @staticmethod
    def _extract_response_text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates", [])
        if not isinstance(candidates, list) or not candidates:
            raise GeminiError("Gemini response missing candidates")
        first_candidate = candidates[0]
        if not isinstance(first_candidate, dict):
            raise GeminiError("Gemini response candidate malformed")
        content = first_candidate.get("content", {})
        if not isinstance(content, dict):
            raise GeminiError("Gemini response content malformed")
        parts = content.get("parts", [])
        if not isinstance(parts, list) or not parts:
            raise GeminiError("Gemini response content parts missing")
        text_parts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        combined = "".join(str(part) for part in text_parts).strip()
        if not combined:
            raise GeminiError("Gemini response text part missing")
        return combined

    @staticmethod
    def _parse_translations_payload(response_text: str) -> list[str]:
        stripped = response_text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise GeminiError("Gemini response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise GeminiError("Gemini response payload is not an object")
        translations = payload.get("translations")
        if not isinstance(translations, list):
            raise GeminiError("Gemini response translations missing")
        return [str(item).strip() for item in translations]

    def _request_json(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> dict[str, Any]:
        for attempt in range(self.MAX_RETRY_ATTEMPTS + 1):
            try:
                return self._request_json_once(method, path, body)
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                if exc.code == 429 and self._is_model_quota_exhausted_detail(detail):
                    raise GeminiError(
                        f"Gemini request failed: {exc.code} {detail}"
                    ) from exc
                if exc.code == 429 and attempt < self.MAX_RETRY_ATTEMPTS:
                    retry_delay = self._extract_retry_delay_seconds(detail)
                    fallback_delay = min(2**attempt, 30)
                    time.sleep(
                        retry_delay if retry_delay is not None else fallback_delay
                    )
                    continue
                raise GeminiError(
                    f"Gemini request failed: {exc.code} {detail}"
                ) from exc
            except error.URLError as exc:
                raise GeminiError(f"Gemini request failed: {exc.reason}") from exc

        raise GeminiError("Gemini request failed after retries")

    def _request_json_once(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> dict[str, Any]:
        query = parse.urlencode({"key": self.api_key})
        url = f"{self.base_url}{path}?{query}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = request.Request(
            url=url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise GeminiError("Gemini response payload is not an object")
            return payload

    def _resolve_generation_model(self, refresh: bool = False) -> str:
        if (
            self._resolved_model is not None
            and not refresh
            and not self._is_model_temporarily_unavailable(self._resolved_model)
        ):
            return self._resolved_model

        requested_model = self.model.strip().removeprefix("models/")
        try:
            models = self.list_models()
        except GeminiError:
            self._resolved_model = requested_model
            return requested_model

        ranked_models = self._rank_candidate_models(
            requested_model,
            models,
            prefer_low_quota_risk=True,
        )
        resolved_model = next(
            (
                model.model_id
                for model in ranked_models
                if not self._is_model_temporarily_unavailable(model.model_id)
            ),
            None,
        )
        self._resolved_model = resolved_model or requested_model
        return self._resolved_model

    def _resolve_alternate_generation_model(
        self, *, excluded_models: set[str], refresh: bool = False
    ) -> str:
        requested_model = self.model.strip().removeprefix("models/")
        try:
            models = self.list_models()
        except GeminiError:
            return next(iter(excluded_models))

        ranked_models = self._rank_candidate_models(
            requested_model,
            models,
            prefer_low_quota_risk=True,
        )
        for model in ranked_models:
            if model.model_id in excluded_models:
                continue
            if self._is_model_temporarily_unavailable(model.model_id):
                continue
            self._resolved_model = model.model_id
            return model.model_id
        return next(iter(excluded_models))

    @staticmethod
    def _match_requested_model(
        requested_model: str, models: list[GeminiModelInfo]
    ) -> str | None:
        ranked_models = GeminiClient._rank_candidate_models(requested_model, models)
        if not ranked_models:
            return None
        return ranked_models[0].model_id

    @staticmethod
    def _rank_candidate_models(
        requested_model: str,
        models: list[GeminiModelInfo],
        prefer_low_quota_risk: bool = False,
    ) -> list[GeminiModelInfo]:
        if not models:
            return []

        exact_match = next(
            (model.model_id for model in models if model.model_id == requested_model),
            None,
        )
        if exact_match is not None and not prefer_low_quota_risk:
            return [model for model in models if model.model_id == exact_match] + [
                model for model in models if model.model_id != exact_match
            ]

        requested_key = GeminiClient._normalize_model_key(requested_model)
        ranked: list[tuple[int, GeminiModelInfo]] = []
        for model in models:
            model_key = GeminiClient._normalize_model_key(model.model_id)
            score = 0
            if model.model_id.startswith(requested_model):
                score += 100
            if requested_key == model_key:
                score += 90
            requested_tokens = requested_key.split("-")
            score += sum(
                10 for token in requested_tokens if token and token in model_key
            )
            if "flash" in requested_key and "flash" in model_key:
                score += 25
            if "pro" in requested_key and "pro" in model_key:
                score += 25
            if prefer_low_quota_risk:
                if "flash" in model_key:
                    score += 90
                if "lite" in model_key:
                    score += 60
                if "pro" in model_key:
                    score -= 220
            if score > 0:
                ranked.append((score, model))

        if not ranked:
            return []

        ranked.sort(key=lambda item: (-item[0], item[1].model_id))
        return [item[1] for item in ranked]

    @staticmethod
    def _normalize_model_key(model_id: str) -> str:
        normalized = model_id.lower().removeprefix("models/")
        normalized = normalized.replace(".", "-")
        normalized = re.sub(r"-preview(?:-[0-9]{2}-[0-9]{2})?", "", normalized)
        normalized = re.sub(r"-[0-9]{3}$", "", normalized)
        normalized = re.sub(r"-+", "-", normalized).strip("-")
        return normalized

    @staticmethod
    def _is_model_not_found_error(exc: GeminiError) -> bool:
        message = str(exc)
        return (
            " 404 " in message and "models/" in message and "generateContent" in message
        )

    @classmethod
    def _supports_text_generation_model(cls, model_name: str) -> bool:
        normalized = model_name.lower()
        return not any(marker in normalized for marker in cls.NON_TEXT_MODEL_MARKERS)

    @staticmethod
    def _is_invalid_text_modality_error(exc: GeminiError) -> bool:
        message = str(exc)
        normalized = message.lower()
        return (
            " 400 " in message
            and "response modalities" in normalized
            and "text" in normalized
            and "not supported by the model" in normalized
        )

    def _mark_model_temporarily_unavailable(
        self, model_id: str, exc: GeminiError
    ) -> None:
        retry_delay = self._extract_retry_delay_seconds(str(exc)) or 60.0
        self._temporarily_unavailable_models[model_id] = time.time() + retry_delay

    def _is_model_temporarily_unavailable(self, model_id: str) -> bool:
        unavailable_until = self._temporarily_unavailable_models.get(model_id)
        if unavailable_until is None:
            return False
        if unavailable_until <= time.time():
            self._temporarily_unavailable_models.pop(model_id, None)
            return False
        return True

    @staticmethod
    def _is_model_quota_exhausted_error(exc: GeminiError) -> bool:
        message = str(exc)
        return GeminiClient._is_model_quota_exhausted_detail(message)

    @staticmethod
    def _is_model_quota_exhausted_detail(detail: str) -> bool:
        message = detail.lower()
        return (
            "quota exceeded for metric" in message
            and "generate_content" in message
            and "model" in message
        )

    @staticmethod
    def _extract_retry_delay_seconds(detail: str) -> float | None:
        try:
            payload = json.loads(detail)
            if isinstance(payload, dict):
                error_payload = payload.get("error", {})
                if isinstance(error_payload, dict):
                    details = error_payload.get("details", [])
                    if isinstance(details, list):
                        for item in details:
                            if not isinstance(item, dict):
                                continue
                            retry_delay = item.get("retryDelay")
                            if isinstance(retry_delay, str):
                                seconds = GeminiClient._parse_duration_seconds(
                                    retry_delay
                                )
                                if seconds is not None:
                                    return seconds
        except json.JSONDecodeError:
            pass

        match = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", detail, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _parse_duration_seconds(value: str) -> float | None:
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)s", value.strip())
        if not match:
            return None
        return float(match.group(1))
# === ANCHOR: TRANSLATOR_GEMINI_END ===
