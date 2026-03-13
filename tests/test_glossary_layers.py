from pathlib import Path
import json

from harmony_translate.glossary import (
    extract_glossary_candidates,
    load_domain_terms,
    load_glossary,
    load_glossary_layers,
    save_glossary,
)


def test_load_glossary_layers_project_overrides_global(tmp_path: Path) -> None:
    global_path = tmp_path / "global.tsv"
    project_path = tmp_path / "project.tsv"
    global_path.write_text("Node View\t노드 뷰\nPeg\t페그\n", encoding="utf-8")
    project_path.write_text("Peg\t리그 페그\n", encoding="utf-8")

    merged = load_glossary_layers([global_path, project_path])

    assert merged["Node View"] == "노드 뷰"
    assert merged["Peg"] == "리그 페그"


def test_save_glossary_creates_tsv_and_roundtrips(tmp_path: Path) -> None:
    glossary_path = tmp_path / "glossary" / "projects" / "HH0304" / "glossary.tsv"
    glossary = {
        "Cutter": "커터",
        "Node View": "노드 뷰",
    }

    save_glossary(glossary_path, glossary)
    loaded = load_glossary(glossary_path)

    assert loaded == glossary


def test_extract_glossary_candidates_finds_basic_terms() -> None:
    values = [
        "Open Node View and adjust SFX timing.",
        "Node View cleanup for Composite node.",
        "Check SFX and BG before export.",
    ]

    candidates = extract_glossary_candidates(values, limit=20)

    assert "Node View" in candidates
    assert "SFX" in candidates


def test_extract_glossary_candidates_filters_non_domain_words() -> None:
    values = [
        "please check lunch menu before meeting",
        "camera movement needs smoother acting timing",
        "the weather is good today",
    ]

    candidates = extract_glossary_candidates(values, limit=50)

    assert "Camera" in candidates
    assert "Timing" in candidates
    assert "Lunch" not in candidates
    assert "Weather" not in candidates


def test_load_domain_terms_supports_project_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "domain_terms.json"
    config_path.write_text(
        json.dumps(
            {
                "domain_keywords": ["node"],
                "domain_acronyms": ["bg"],
                "blocked": ["open"],
                "projects": {
                    "PROJX": {
                        "domain_keywords": ["camera"],
                        "domain_acronyms": ["mat"],
                        "blocked": ["check"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    base_keywords, base_acronyms, base_blocked = load_domain_terms(config_path)
    project_keywords, project_acronyms, project_blocked = load_domain_terms(
        config_path, "PROJX"
    )

    assert "node" in base_keywords
    assert "camera" not in base_keywords
    assert "BG" in base_acronyms
    assert "check" not in base_blocked

    assert "camera" in project_keywords
    assert "MAT" in project_acronyms
    assert "check" in project_blocked


def test_extract_glossary_candidates_can_use_custom_json_config(tmp_path: Path) -> None:
    config_path = tmp_path / "domain_terms.json"
    config_path.write_text(
        json.dumps(
            {
                "domain_keywords": ["node"],
                "domain_acronyms": ["bg"],
                "blocked": ["open"],
                "projects": {"CAMPROJ": {"domain_keywords": ["camera"]}},
            }
        ),
        encoding="utf-8",
    )

    values = [
        "Open Node View with BG pass.",
        "Camera movement looks smooth.",
    ]

    base_candidates = extract_glossary_candidates(
        values,
        limit=40,
        domain_terms_path=config_path,
    )
    project_candidates = extract_glossary_candidates(
        values,
        limit=40,
        domain_terms_path=config_path,
        project_id="CAMPROJ",
    )

    assert "Node View" in base_candidates
    assert "BG" in base_candidates
    assert "Camera" not in base_candidates
    assert "Camera" in project_candidates
