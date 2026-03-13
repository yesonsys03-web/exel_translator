from __future__ import annotations

import os
from pathlib import Path

import harmony_translate.config as config_module
from harmony_translate.cli import build_config
from harmony_translate.config import deepl_enabled, load_env_file, normalize_provider


def test_load_env_file_replaces_empty_existing_value(
    monkeypatch, tmp_path: Path
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("GEMINI_API_KEY=real-key\n", encoding="utf-8")

    monkeypatch.setenv("GEMINI_API_KEY", "")
    load_env_file(env_path)

    assert os.environ.get("GEMINI_API_KEY") == "real-key"


def test_load_env_file_keeps_non_empty_existing_value(
    monkeypatch, tmp_path: Path
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("GEMINI_API_KEY=file-key\n", encoding="utf-8")

    monkeypatch.setenv("GEMINI_API_KEY", "shell-key")
    load_env_file(env_path)

    assert os.environ.get("GEMINI_API_KEY") == "shell-key"


def test_load_env_file_uses_project_root_fallback(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    env_path = project_root / ".env"
    env_path.write_text("GEMINI_API_KEY=fallback-key\n", encoding="utf-8")

    monkeypatch.setattr(config_module, "PROJECT_ROOT", project_root)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.chdir(tmp_path)

    load_env_file(Path(".env"))

    assert os.environ.get("GEMINI_API_KEY") == "fallback-key"


def test_normalize_provider_disables_deepl() -> None:
    assert normalize_provider("deepl") == "gemini"
    assert normalize_provider("gemini") == "gemini"
    assert normalize_provider("") == "gemini"


def test_deepl_feature_flag_enables_deepl_provider(monkeypatch) -> None:
    monkeypatch.setenv("TRANSLATION_ENABLE_DEEPL", "true")

    assert deepl_enabled() is True
    assert normalize_provider("deepl") == "deepl"


def test_build_config_falls_back_to_gemini_when_deepl_requested(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRANSLATION_PROVIDER", "deepl")

    config = build_config(
        input_path=tmp_path / "input.xlsx",
        output_dir=tmp_path / "out",
        sheet_name=None,
        selected_columns=[],
        preserve_original_sheet=False,
        mapped_cell_mode="translation_only",
        glossary_path=tmp_path / "glossary.tsv",
        exclude_patterns_path=tmp_path / "exclude_patterns.yaml",
        source_lang="EN",
        target_lang="KO",
        provider="deepl",
        gemini_model="gemini-3-flash",
        cache_path=tmp_path / "cache.sqlite3",
        env_file=tmp_path / ".env",
    )

    assert config.provider == "gemini"


def test_build_config_accepts_deepl_when_feature_flag_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TRANSLATION_ENABLE_DEEPL", "true")

    config = build_config(
        input_path=tmp_path / "input.xlsx",
        output_dir=tmp_path / "out",
        sheet_name=None,
        selected_columns=[],
        preserve_original_sheet=False,
        mapped_cell_mode="translation_only",
        glossary_path=tmp_path / "glossary.tsv",
        exclude_patterns_path=tmp_path / "exclude_patterns.yaml",
        source_lang="EN",
        target_lang="KO",
        provider="deepl",
        gemini_model="gemini-3-flash",
        cache_path=tmp_path / "cache.sqlite3",
        env_file=tmp_path / ".env",
    )

    assert config.provider == "deepl"
