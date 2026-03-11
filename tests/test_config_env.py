from __future__ import annotations

import os
from pathlib import Path

import harmony_translate.config as config_module
from harmony_translate.config import load_env_file


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
