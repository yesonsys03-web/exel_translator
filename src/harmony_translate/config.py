# === ANCHOR: CONFIG_START ===
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TRUE_VALUES = {"1", "true", "yes", "on"}


def deepl_enabled() -> bool:
    raw_value = os.environ.get("TRANSLATION_ENABLE_DEEPL", "")
    return raw_value.strip().lower() in _TRUE_VALUES


def supported_providers() -> tuple[str, ...]:
    if deepl_enabled():
        return ("gemini", "deepl")
    return ("gemini",)


def normalize_provider(provider: str | None, fallback: str = "gemini") -> str:
    providers = supported_providers()
    normalized = (provider or "").strip().lower()
    if normalized in providers:
        return normalized
    normalized_fallback = (fallback or "").strip().lower()
    if normalized_fallback in providers:
        return normalized_fallback
    return providers[0]


@dataclass
class AppConfig:
    input_path: Path
    output_dir: Path
    sheet_name: str | None
    selected_columns: list[str]
    preserve_original_sheet: bool
    mapped_cell_mode: str
    glossary_path: Path
    exclude_patterns_path: Path
    target_lang: str
    source_lang: str
    provider: str
    deepl_api_key: str
    deepl_base_url: str
    gemini_api_key: str
    gemini_model: str
    gemini_base_url: str
    cache_path: Path

    @property
    def preview_mode(self) -> bool:
        provider = self.provider.strip().lower()
        if provider == "gemini":
            return not self.gemini_api_key.strip()
        return not self.deepl_api_key.strip()


def load_env_file(env_path: Path) -> None:
    resolved_env_path = _resolve_env_path(env_path)
    if not resolved_env_path.exists():
        return

    for raw_line in resolved_env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        normalized_value = value.strip()
        current_value = os.environ.get(normalized_key)
        if current_value is None or current_value == "":
            os.environ[normalized_key] = normalized_value


def _resolve_env_path(env_path: Path) -> Path:
    if env_path.is_absolute() or env_path.exists():
        return env_path
    return PROJECT_ROOT / env_path
# === ANCHOR: CONFIG_END ===
