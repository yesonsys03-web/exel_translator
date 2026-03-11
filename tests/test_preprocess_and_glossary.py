from harmony_translate.glossary import apply_term_locks
from harmony_translate.preprocess import build_deduplicated_texts, normalize_text


def test_normalize_text_compacts_whitespace() -> None:
    assert normalize_text(" Hello   world\r\n\r\n") == "Hello world"


def test_build_deduplicated_texts_preserves_uniques() -> None:
    unique_texts, _ = build_deduplicated_texts(["A", " A ", "B"])
    assert unique_texts == ["A", "B"]


def test_apply_term_locks_replaces_known_terms() -> None:
    glossary = {"Node View": "노드 뷰", "Cutter": "커터"}
    result = apply_term_locks("Open Node View and add Cutter.", glossary)
    assert result == "Open 노드 뷰 and add 커터."
