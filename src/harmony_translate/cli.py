from __future__ import annotations

import argparse
from pathlib import Path

from harmony_translate.config import (
    AppConfig,
    load_env_file,
    normalize_provider,
)
from harmony_translate.pipeline import run_pipeline


DEFAULT_INPUT_PATH = Path(
    "/Volumes/bgfinal/colordata/Hazbin_Hotel/HH03/HH0304/Leadsheet/HH0304-Episodic_Lead_Sheet_LIVE_Yeson.xlsx"
)


def build_config(
    *,
    input_path: Path,
    output_dir: Path,
    sheet_name: str | None,
    selected_columns: list[str],
    preserve_original_sheet: bool,
    mapped_cell_mode: str,
    glossary_path: Path,
    exclude_patterns_path: Path,
    source_lang: str,
    target_lang: str,
    provider: str,
    gemini_model: str,
    cache_path: Path,
    env_file: Path,
    global_glossary_path: Path | None = None,
    project_id: str = "",
) -> AppConfig:
    # [ANCHOR:CLI_BUILD_CONFIG]
    load_env_file(env_file)
    from os import environ

    api_key = environ.get("DEEPL_API_KEY", "")
    base_url = environ.get("DEEPL_BASE_URL", "https://api-free.deepl.com")
    gemini_api_key = environ.get("GEMINI_API_KEY", "")
    gemini_base_url = environ.get(
        "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com"
    )
    env_provider = normalize_provider(environ.get("TRANSLATION_PROVIDER", "gemini"))
    resolved_provider = normalize_provider(
        provider if provider else env_provider,
        fallback=env_provider,
    )
    return AppConfig(
        input_path=input_path,
        output_dir=output_dir,
        sheet_name=sheet_name,
        selected_columns=selected_columns,
        preserve_original_sheet=preserve_original_sheet,
        mapped_cell_mode=mapped_cell_mode,
        glossary_path=glossary_path,
        exclude_patterns_path=exclude_patterns_path,
        target_lang=target_lang,
        source_lang=source_lang,
        provider=resolved_provider,
        deepl_api_key=api_key,
        deepl_base_url=base_url,
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        gemini_base_url=gemini_base_url,
        cache_path=cache_path,
        global_glossary_path=global_glossary_path,
        project_id=project_id,
    )


def build_parser() -> argparse.ArgumentParser:
    # [ANCHOR:MAIN_CLI_ENTRY]
    parser = argparse.ArgumentParser(
        description="Translate selected Excel columns with Gemini"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(DEFAULT_INPUT_PATH),
        help="Path to input xlsx file",
    )
    parser.add_argument(
        "--output-dir", default="output", help="Directory for translated artifacts"
    )
    parser.add_argument("--sheet", default=None, help="Optional sheet name")
    parser.add_argument(
        "--preserve-original-sheet",
        action="store_true",
        help="Keep a backup sheet with original source text in <source>_KO.xlsx",
    )
    parser.add_argument(
        "--mapped-cell-mode",
        default="translation_only",
        choices=["translation_only", "original_and_translation"],
        help="How <source>_KO.xlsx cells should display translated content",
    )
    parser.add_argument(
        "--columns",
        default="",
        help="Comma-separated header names. If omitted, columns are auto-selected.",
    )
    parser.add_argument(
        "--glossary", default="glossary.tsv", help="Path to glossary TSV"
    )
    parser.add_argument(
        "--global-glossary",
        default="",
        help="Optional global glossary TSV path (applied before --glossary)",
    )
    parser.add_argument(
        "--project-id",
        default="",
        help="Optional project id for project-scoped glossary/cache separation",
    )
    parser.add_argument(
        "--exclude-patterns",
        default="exclude_patterns.yaml",
        help="Path to exclusion YAML",
    )
    parser.add_argument("--source-lang", default="EN", help="Source language")
    parser.add_argument("--target-lang", default="KO", help="Target language")
    parser.add_argument(
        "--provider",
        default="gemini",
        help="Translation provider (deepl requires TRANSLATION_ENABLE_DEEPL=true)",
    )
    parser.add_argument(
        "--gemini-model",
        default="gemini-2.5-flash",
        help="Gemini model id for Google AI Studio provider",
    )
    parser.add_argument("--env-file", default=".env", help="Optional env file path")
    parser.add_argument(
        "--cache-path",
        default=".cache/translations.sqlite3",
        help="Path to sqlite cache",
    )
    return parser


def main() -> int:
    # [ANCHOR:MAIN_PARSE_AND_RUN]
    parser = build_parser()
    args = parser.parse_args()
    selected_columns = [
        part.strip() for part in args.columns.split(",") if part.strip()
    ]

    config = build_config(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        sheet_name=args.sheet,
        selected_columns=selected_columns,
        preserve_original_sheet=args.preserve_original_sheet,
        mapped_cell_mode=args.mapped_cell_mode,
        glossary_path=Path(args.glossary),
        exclude_patterns_path=Path(args.exclude_patterns),
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        provider=args.provider,
        gemini_model=args.gemini_model,
        cache_path=Path(args.cache_path),
        env_file=Path(args.env_file),
        global_glossary_path=(
            Path(args.global_glossary.strip())
            if str(args.global_glossary).strip()
            else None
        ),
        project_id=str(args.project_id).strip(),
    )
    result = run_pipeline(config, log_callback=print)
    if result.preview_mode:
        missing_key_name = (
            "GEMINI_API_KEY" if config.provider == "gemini" else "DEEPL_API_KEY"
        )
        print(
            f"Preview mode: {missing_key_name} not set, translation API calls were skipped."
        )
    print(f"Translated workbook: {result.translated_path}")
    print(f"Source mapped workbook: {result.source_mapped_path}")
    print(f"Audit workbook: {result.audit_path}")
    print(f"Usage report: {result.usage_path}")
    print(f"Selected headers: {', '.join(result.selected_headers)}")
    return 0
