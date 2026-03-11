from __future__ import annotations

from collections import OrderedDict
import re


def normalize_text(value: str) -> str:
    # [ANCHOR:PREPROCESS_NORMALIZE_TEXT]
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def build_deduplicated_texts(values: list[str]) -> tuple[list[str], dict[str, str]]:
    # [ANCHOR:PREPROCESS_DEDUP]
    ordered_unique: OrderedDict[str, str] = OrderedDict()
    for original in values:
        normalized = normalize_text(original)
        if normalized and normalized not in ordered_unique:
            ordered_unique[normalized] = original
    return list(ordered_unique.keys()), {
        normalize_text(v): normalize_text(v) for v in values if normalize_text(v)
    }


def looks_like_code(value: str, patterns: list[re.Pattern[str]]) -> bool:
    # [ANCHOR:PREPROCESS_LOOKS_LIKE_CODE]
    text = normalize_text(value)
    if not text:
        return False
    return any(pattern.search(text) for pattern in patterns)
