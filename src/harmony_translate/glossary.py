from __future__ import annotations

from collections import Counter
from pathlib import Path
import csv
import json
import re


DEFAULT_DOMAIN_TERMS_PATH = Path("domain_terms.json")
DEFAULT_DOMAIN_KEYWORDS = {
    "node",
    "view",
    "camera",
    "movement",
    "timing",
    "acting",
    "composite",
    "scene",
    "shot",
    "background",
    "animation",
    "effect",
    "effects",
    "render",
    "export",
    "cleanup",
    "layer",
    "peg",
    "cutter",
    "timeline",
    "frame",
    "keyframe",
    "drawing",
    "deform",
    "rig",
    "palette",
    "exposure",
    "xsheet",
    "ink",
    "paint",
    "pass",
}
DEFAULT_DOMAIN_ACRONYMS = {
    "BG",
    "FX",
    "SFX",
    "FG",
    "VFX",
    "OGL",
    "USD",
}
DEFAULT_BLOCKED_WORDS = {
    "the",
    "and",
    "or",
    "to",
    "for",
    "with",
    "from",
    "this",
    "that",
    "there",
    "where",
    "before",
    "after",
    "check",
    "adjust",
    "open",
}


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


def load_glossary_layers(glossary_paths: list[Path]) -> dict[str, str]:
    # [ANCHOR:GLOSSARY_LOAD_LAYERS]
    merged: dict[str, str] = {}
    for glossary_path in glossary_paths:
        merged.update(load_glossary(glossary_path))
    return merged


def save_glossary(glossary_path: Path, glossary: dict[str, str]) -> None:
    # [ANCHOR:GLOSSARY_SAVE_TSV]
    glossary_path.parent.mkdir(parents=True, exist_ok=True)
    with glossary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        for source, target in sorted(glossary.items()):
            writer.writerow([source, target])


def load_domain_terms(
    domain_terms_path: Path | None = None,
    project_id: str = "",
) -> tuple[set[str], set[str], set[str]]:
    # [ANCHOR:GLOSSARY_LOAD_DOMAIN_TERMS]
    domain_keywords = set(DEFAULT_DOMAIN_KEYWORDS)
    domain_acronyms = set(DEFAULT_DOMAIN_ACRONYMS)
    blocked_words = set(DEFAULT_BLOCKED_WORDS)
    config_path = domain_terms_path or DEFAULT_DOMAIN_TERMS_PATH
    if not config_path.exists():
        return domain_keywords, domain_acronyms, blocked_words

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return domain_keywords, domain_acronyms, blocked_words
    if not isinstance(payload, dict):
        return domain_keywords, domain_acronyms, blocked_words

    domain_keywords.update(_read_set(payload, "domain_keywords", transform=str.lower))
    domain_acronyms.update(_read_set(payload, "domain_acronyms", transform=str.upper))
    blocked_words.update(_read_set(payload, "blocked", transform=str.lower))

    projects = payload.get("projects")
    if isinstance(projects, dict) and project_id:
        project_payload = projects.get(project_id)
        if isinstance(project_payload, dict):
            domain_keywords.update(
                _read_set(project_payload, "domain_keywords", transform=str.lower)
            )
            domain_acronyms.update(
                _read_set(project_payload, "domain_acronyms", transform=str.upper)
            )
            blocked_words.update(
                _read_set(project_payload, "blocked", transform=str.lower)
            )

    return domain_keywords, domain_acronyms, blocked_words


def _read_set(payload: dict[str, object], key: str, transform) -> set[str]:
    raw_values = payload.get(key)
    if not isinstance(raw_values, list):
        return set()
    normalized_values: set[str] = set()
    for item in raw_values:
        if not isinstance(item, str):
            continue
        value = transform(item.strip())
        if value:
            normalized_values.add(value)
    return normalized_values


def extract_glossary_candidates(
    values: list[str],
    limit: int = 120,
    *,
    domain_terms_path: Path | None = None,
    project_id: str = "",
) -> list[str]:
    # [ANCHOR:GLOSSARY_EXTRACT_CANDIDATES]
    token_counter: Counter[str] = Counter()
    acronym_pattern = re.compile(r"\b[A-Z]{2,6}\b")
    phrase_pattern = re.compile(r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b")
    word_pattern = re.compile(r"\b[a-zA-Z]{4,}\b")
    domain_keywords, domain_acronyms, blocked_words = load_domain_terms(
        domain_terms_path, project_id
    )

    for value in values:
        for candidate in acronym_pattern.findall(value):
            if candidate.upper() not in domain_acronyms:
                continue
            token_counter[candidate.upper()] += 1
        for candidate in phrase_pattern.findall(value):
            normalized = candidate.strip()
            if normalized.lower() in blocked_words:
                continue
            if normalized.isdigit():
                continue
            words = [word.lower() for word in re.findall(r"[A-Za-z]+", normalized)]
            if not any(word in domain_keywords for word in words):
                continue
            token_counter[normalized] += 1

        lowered_tokens = [token.lower() for token in word_pattern.findall(value)]
        for token in lowered_tokens:
            if token not in domain_keywords:
                continue
            normalized = token.capitalize()
            if normalized.lower() in blocked_words:
                continue
            token_counter[normalized] += 1

        for index in range(len(lowered_tokens) - 1):
            left = lowered_tokens[index]
            right = lowered_tokens[index + 1]
            if left not in domain_keywords or right not in domain_keywords:
                continue
            if left == right:
                continue
            if left in blocked_words or right in blocked_words:
                continue
            token_counter[f"{left.capitalize()} {right.capitalize()}"] += 1

    ranked = sorted(token_counter.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _ in ranked[:limit]]


def apply_term_locks(text: str, glossary: dict[str, str]) -> str:
    # [ANCHOR:GLOSSARY_APPLY_LOCK]
    result = text
    for source, target in sorted(
        glossary.items(), key=lambda item: len(item[0]), reverse=True
    ):
        pattern = re.compile(rf"\b{re.escape(source)}\b")
        result = pattern.sub(target, result)
    return result
