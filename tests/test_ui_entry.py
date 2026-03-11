from pathlib import Path
import importlib.util

import pytest
from openpyxl import Workbook
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from harmony_translate.cli import DEFAULT_INPUT_PATH, build_parser
from harmony_translate.ui import MainWindow, USER_ROLE


def load_main_module():
    module_path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("main_module", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parser_default_input_still_matches_sample() -> None:
    parser = build_parser()
    args = parser.parse_args([])
    assert args.input == str(DEFAULT_INPUT_PATH)


def test_main_exposes_gui_launcher() -> None:
    module = load_main_module()
    assert callable(module.launch_ui)


def test_main_window_populates_sheet_selector_from_workbook(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    workbook = Workbook()
    sheet1 = workbook.active
    assert sheet1 is not None
    sheet1.title = "Sheet1"
    workbook.create_sheet("Notes")
    sheet1["A13"] = "SHOT CODE"
    sheet1["P13"] = "ANIMATION"
    sheet1["A14"] = "HH0304_010_0010"
    sheet1["P14"] = "Test note"
    path = tmp_path / "ui-sheets.xlsx"
    workbook.save(path)

    window = MainWindow()
    window.input_edit.setText(str(path))
    window.load_workbook_preview()

    sheet_names = [
        window.sheet_combo.itemText(index)
        for index in range(window.sheet_combo.count())
    ]
    assert sheet_names == ["Sheet1", "Notes"]
    assert window.get_selected_sheet_name() == "Sheet1"
    column_labels = []
    for index in range(window.column_list.count()):
        item = window.column_list.item(index)
        assert item is not None
        column_labels.append(item.text())
    assert any(label.startswith("A | SHOT CODE") for label in column_labels)
    assert any(label.startswith("P | ANIMATION") for label in column_labels)
    assert window.preview_table.columnCount() >= 2
    assert window.preview_table.rowCount() >= 1
    header_labels = []
    for index in range(window.preview_table.columnCount()):
        header_item = window.preview_table.horizontalHeaderItem(index)
        if header_item is None:
            continue
        header_labels.append(header_item.text())
    assert any(label.endswith("SHOT CODE") for label in header_labels)
    assert any(label.endswith("ANIMATION") for label in header_labels)
    first_row_value = window.preview_table.item(0, 0)
    assert first_row_value is not None
    assert first_row_value.text() == "HH0304_010_0010"
    window.close()
    app.quit()


def test_column_list_selection_focuses_matching_preview_column(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    workbook = Workbook()
    sheet1 = workbook.active
    assert sheet1 is not None
    sheet1.title = "Sheet1"
    sheet1["A13"] = "SHOT CODE"
    sheet1["P13"] = "ANIMATION"
    sheet1["Y13"] = "NOTES"
    sheet1["A14"] = "HH0304_010_0010"
    sheet1["P14"] = "Test animation note"
    sheet1["Y14"] = "Test notes column"
    path = tmp_path / "ui-focus.xlsx"
    workbook.save(path)

    window = MainWindow()
    window.input_edit.setText(str(path))
    window.load_workbook_preview()

    target_item = None
    for index in range(window.column_list.count()):
        item = window.column_list.item(index)
        assert item is not None
        if str(item.data(USER_ROLE)).startswith("P | ANIMATION"):
            target_item = item
            break
    assert target_item is not None

    window.column_list.setCurrentItem(target_item)

    current_column = window.preview_table.currentColumn()
    header_item = window.preview_table.horizontalHeaderItem(current_column)
    assert header_item is not None
    assert header_item.text().startswith("P | ANIMATION")
    window.close()
    app.quit()


def test_selected_column_character_count_updates_live(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    workbook = Workbook()
    sheet1 = workbook.active
    assert sheet1 is not None
    sheet1.title = "Sheet1"
    sheet1["A13"] = "SHOT CODE"
    sheet1["P13"] = "ANIMATION"
    sheet1["Y13"] = "NOTES"
    sheet1["A14"] = "HH0304_010_0010"
    sheet1["P14"] = "Alpha"
    sheet1["Y14"] = "BetaBeta"
    sheet1["A15"] = "HH0304_010_0020"
    sheet1["P15"] = "Gamma"
    sheet1["Y15"] = "Delta"
    path = tmp_path / "ui-char-count.xlsx"
    workbook.save(path)

    window = MainWindow()
    window.input_edit.setText(str(path))
    window.load_workbook_preview()

    target_item = None
    for index in range(window.column_list.count()):
        item = window.column_list.item(index)
        assert item is not None
        if str(item.data(USER_ROLE)).startswith("P | ANIMATION"):
            target_item = item
            break
    assert target_item is not None

    target_item.setCheckState(Qt.CheckState.Unchecked)
    text_without_p = window.selection_stats_label.text()
    target_item.setCheckState(Qt.CheckState.Checked)
    text_with_p = window.selection_stats_label.text()

    assert "총 글자 수" in text_without_p
    assert "총 글자 수" in text_with_p
    assert text_with_p != text_without_p

    window.close()
    app.quit()


def test_selection_stats_shows_dynamic_deepl_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    workbook = Workbook()
    sheet1 = workbook.active
    assert sheet1 is not None
    sheet1.title = "Sheet1"
    sheet1["A13"] = "SHOT CODE"
    sheet1["P13"] = "ANIMATION"
    sheet1["A14"] = "HH0304_010_0010"
    sheet1["P14"] = "Alpha"
    path = tmp_path / "ui-dynamic-limit.xlsx"
    workbook.save(path)

    class FakeDeepLClient:
        def __init__(self, api_key: str, base_url: str) -> None:
            self.api_key = api_key
            self.base_url = base_url

        def usage(self):
            class Usage:
                character_count = 123456
                character_limit = 750000

            return Usage()

    monkeypatch.setenv("DEEPL_API_KEY", "test-key")
    monkeypatch.setattr("harmony_translate.ui.DeepLClient", FakeDeepLClient)

    window = MainWindow()
    window.input_edit.setText(str(path))
    window.load_workbook_preview()

    stats_text = window.selection_stats_label.text()
    assert "123,456/750,000자" in stats_text
    assert "남은 626,544자" in stats_text

    window.close()
    app.quit()


def test_gemini_provider_shows_model_token_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = QApplication.instance() or QApplication([])
    workbook = Workbook()
    sheet1 = workbook.active
    assert sheet1 is not None
    sheet1.title = "Sheet1"
    sheet1["A13"] = "SHOT CODE"
    sheet1["P13"] = "ANIMATION"
    sheet1["A14"] = "HH0304_010_0010"
    sheet1["P14"] = "Alpha"
    path = tmp_path / "ui-gemini-limit.xlsx"
    workbook.save(path)

    class FakeModel:
        def __init__(
            self, model_id: str, display_name: str, input_limit: int, output_limit: int
        ) -> None:
            self.model_id = model_id
            self.display_name = display_name
            self.input_token_limit = input_limit
            self.output_token_limit = output_limit

    class FakeGeminiClient:
        def __init__(self, api_key: str, model: str, base_url: str) -> None:
            self.api_key = api_key
            self.model = model
            self.base_url = base_url

        def list_models(self):
            return [
                FakeModel("gemini-2.0-flash", "Gemini 2.0 Flash", 1048576, 8192),
                FakeModel(
                    "gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite", 1048576, 8192
                ),
            ]

    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr("harmony_translate.ui.GeminiClient", FakeGeminiClient)

    window = MainWindow()
    window.input_edit.setText(str(path))
    provider_index = window.provider_combo.findData("gemini")
    assert provider_index >= 0
    window.provider_combo.setCurrentIndex(provider_index)
    window.load_workbook_preview()

    stats_text = window.selection_stats_label.text()
    assert "Gemini gemini-2.0-flash 제한 입력 1,048,576tok" in stats_text
    assert "출력 8,192tok" in stats_text

    window.close()
    app.quit()


def test_progress_bar_updates_from_worker_signal(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    workbook = Workbook()
    sheet1 = workbook.active
    assert sheet1 is not None
    sheet1.title = "Sheet1"
    sheet1["A13"] = "SHOT CODE"
    sheet1["P13"] = "ANIMATION"
    sheet1["A14"] = "HH0304_010_0010"
    sheet1["P14"] = "Alpha"
    path = tmp_path / "ui-progress.xlsx"
    workbook.save(path)

    window = MainWindow()
    window.input_edit.setText(str(path))
    window.load_workbook_preview()

    window.handle_run_progress_value(42)

    assert window.progress_bar.value() == 42
    assert window.progress_bar.format() == "진행률 42%"

    window.close()
    app.quit()


def test_preserve_original_checkbox_defaults_enabled(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    workbook = Workbook()
    sheet1 = workbook.active
    assert sheet1 is not None
    sheet1.title = "Sheet1"
    sheet1["A13"] = "SHOT CODE"
    sheet1["P13"] = "ANIMATION"
    sheet1["A14"] = "HH0304_010_0010"
    sheet1["P14"] = "Alpha"
    path = tmp_path / "ui-preserve-option.xlsx"
    workbook.save(path)

    window = MainWindow()
    window.input_edit.setText(str(path))
    window.load_workbook_preview()

    assert window.preserve_original_checkbox.isChecked() is True
    assert "Sheet1_ORIGINAL" in window.preserve_original_checkbox.text()

    workbook2 = Workbook()
    second_sheet = workbook2.active
    assert second_sheet is not None
    second_sheet.title = "Dialogue"
    second_sheet["A13"] = "SHOT CODE"
    second_sheet["P13"] = "ANIMATION"
    second_sheet["A14"] = "HH0304_010_0010"
    second_sheet["P14"] = "Beta"
    path2 = tmp_path / "ui-preserve-option-2.xlsx"
    workbook2.save(path2)

    window.input_edit.setText(str(path2))
    window.load_workbook_preview()

    assert "Dialogue_ORIGINAL" in window.preserve_original_checkbox.text()
    assert window.mapped_cell_mode_combo.currentData() == "translation_only"

    window.close()
    app.quit()
