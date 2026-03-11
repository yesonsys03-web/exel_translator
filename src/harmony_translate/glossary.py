from __future__ import annotations

from pathlib import Path
import csv
import re


def load_glossary(glossary_path: Path) -> dict[str, str]:
    # [ANCHOR:GLOSSARY_LOAD_TSV]
    glossary: dict[str, str] = {}
    if not glossary_path.exists():
        return glossary
    with glossary_path.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if len(row) < 2:
                continue
            source = row[0].strip()
            target = row[1].strip()
            if source and target:
                glossary[source] = target
    return glossary


def apply_term_locks(text: str, glossary: dict[str, str]) -> str:
    # [ANCHOR:GLOSSARY_APPLY_LOCK]
    result = text
    for source, target in sorted(
        glossary.items(), key=lambda item: len(item[0]), reverse=True
    ):
        pattern = re.compile(rf"\b{re.escape(source)}\b")
        result = pattern.sub(target, result)
    return result
