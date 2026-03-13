from __future__ import annotations

from dataclasses import dataclass
import difflib
from pathlib import Path
import os
import re
import sys
from importlib import util as importlib_util

from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QCheckBox,
    QPushButton,
    QAbstractItemView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from harmony_translate.cli import DEFAULT_INPUT_PATH, build_config
from harmony_translate.config import deepl_enabled, load_env_file, normalize_provider
from harmony_translate.column_selector import (
    profile_columns,
    select_translation_columns,
)
from harmony_translate.excel_io import (
    build_column_label,
    build_sheet_context,
    build_sheet_preview,
    load_excel_workbook,
)
from harmony_translate.glossary import (
    extract_glossary_candidates,
    load_glossary,
    load_glossary_layers,
    save_glossary,
)
from harmony_translate.pipeline import PipelineResult, run_pipeline
from harmony_translate.translator_deepl import DeepLClient
from harmony_translate.translator_gemini import GeminiClient, GeminiModelInfo
from harmony_translate.preprocess import normalize_text


ITEM_IS_USER_CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable
CHECKED_STATE = Qt.CheckState.Checked
USER_ROLE = Qt.ItemDataRole.UserRole
GLOSSARY_CANDIDATES_ROLE = int(Qt.ItemDataRole.UserRole) + 10
RECOMMENDED_BG = Qt.GlobalColor.yellow
KNOWN_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-3.1-pro-preview",
]
PROJECT_GLOSSARY_ROOT = Path("glossary/projects")


@dataclass
class ColumnSuggestion:
    index: int
    header: str
    label: str
    score: float
    text_count: int
    character_count: int


class PipelineWorker(QObject):
    # [ANCHOR:UI_PIPELINE_WORKER]
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int)

    def __init__(self, config) -> None:
        super().__init__()
        self.config = config

    def run(self) -> None:
        def _emit_progress(message: str) -> None:
            self.progress.emit(message)
            print(message)

        def _emit_progress_value(value: int) -> None:
            self.progress_value.emit(value)

        try:
            result = run_pipeline(
                self.config,
                log_callback=_emit_progress,
                progress_callback=_emit_progress_value,
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class MainWindow(QMainWindow):
    # [ANCHOR:UI_MAIN_WINDOW]
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Harmony Translate")
        self.resize(920, 680)
        self.current_input_path = DEFAULT_INPUT_PATH
        self.worker_thread: QThread | None = None
        self.worker: PipelineWorker | None = None
        self.column_suggestions: list[ColumnSuggestion] = []
        self.available_sheet_names: list[str] = []
        self.preview_column_index_by_label: dict[str, int] = {}
        self.deepl_character_count: int | None = None
        self.deepl_character_limit: int | None = None
        self.gemini_models_by_id: dict[str, GeminiModelInfo] = {}

        load_env_file(Path(".env"))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        form_layout = QGridLayout()
        layout.addLayout(form_layout)

        self.input_edit = QLineEdit(str(DEFAULT_INPUT_PATH))
        browse_input = QPushButton("파일 선택")
        browse_input.clicked.connect(self.choose_input_file)
        form_layout.addWidget(QLabel("입력 엑셀"), 0, 0)
        form_layout.addWidget(self.input_edit, 0, 1)
        form_layout.addWidget(browse_input, 0, 2)

        self.output_edit = QLineEdit(str(Path.cwd() / "output"))
        browse_output = QPushButton("출력 폴더")
        browse_output.clicked.connect(self.choose_output_dir)
        form_layout.addWidget(QLabel("출력 폴더"), 1, 0)
        form_layout.addWidget(self.output_edit, 1, 1)
        form_layout.addWidget(browse_output, 1, 2)

        self.sheet_combo = QComboBox()
        self.sheet_combo.currentIndexChanged.connect(self.handle_sheet_changed)
        form_layout.addWidget(QLabel("시트 선택"), 2, 0)
        form_layout.addWidget(self.sheet_combo, 2, 1, 1, 2)

        self.project_id_edit = QLineEdit("")
        self.project_id_edit.setPlaceholderText("예: HH0304")
        form_layout.addWidget(QLabel("작품 ID"), 3, 0)
        form_layout.addWidget(self.project_id_edit, 3, 1, 1, 2)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Google AI Studio (Gemini)", "gemini")
        if deepl_enabled():
            self.provider_combo.addItem("DeepL", "deepl")
        self.provider_combo.currentIndexChanged.connect(self.handle_provider_changed)
        form_layout.addWidget(QLabel("번역 엔진"), 4, 0)
        form_layout.addWidget(self.provider_combo, 4, 1, 1, 2)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.currentIndexChanged.connect(self.handle_gemini_model_changed)
        form_layout.addWidget(QLabel("Gemini 모델"), 5, 0)
        form_layout.addWidget(self.model_combo, 5, 1, 1, 2)

        self.preserve_original_checkbox = QCheckBox("번역본(_KO.xlsx)에 원문 시트 보존")
        self.preserve_original_checkbox.setChecked(True)
        form_layout.addWidget(self.preserve_original_checkbox, 6, 0, 1, 3)

        self.mapped_cell_mode_combo = QComboBox()
        self.mapped_cell_mode_combo.addItem("번역만 표시", "translation_only")
        self.mapped_cell_mode_combo.addItem(
            "원문 + 번역 함께 표시",
            "original_and_translation",
        )
        form_layout.addWidget(QLabel("번역본(_KO.xlsx) 표시 방식"), 7, 0)
        form_layout.addWidget(self.mapped_cell_mode_combo, 7, 1, 1, 2)

        button_row = QHBoxLayout()
        layout.addLayout(button_row)
        self.load_button = QPushButton("컬럼 분석")
        self.load_button.clicked.connect(self.load_workbook_preview)
        button_row.addWidget(self.load_button)
        self.run_button = QPushButton("실행")
        self.run_button.clicked.connect(self.run_from_ui)
        button_row.addWidget(self.run_button)

        glossary_button_row = QHBoxLayout()
        layout.addLayout(glossary_button_row)
        self.glossary_load_button = QPushButton("용어집 불러오기")
        self.glossary_load_button.clicked.connect(self.load_glossary_editor)
        glossary_button_row.addWidget(self.glossary_load_button)
        self.glossary_save_button = QPushButton("용어집 저장")
        self.glossary_save_button.clicked.connect(self.save_glossary_editor)
        glossary_button_row.addWidget(self.glossary_save_button)
        self.glossary_add_row_button = QPushButton("용어 추가")
        self.glossary_add_row_button.clicked.connect(self.add_glossary_row)
        glossary_button_row.addWidget(self.glossary_add_row_button)
        self.glossary_remove_row_button = QPushButton("용어 삭제")
        self.glossary_remove_row_button.clicked.connect(self.remove_glossary_row)
        glossary_button_row.addWidget(self.glossary_remove_row_button)
        self.glossary_generate_button = QPushButton("자동 용어 생성")
        self.glossary_generate_button.clicked.connect(self.generate_glossary_candidates)
        glossary_button_row.addWidget(self.glossary_generate_button)

        layout.addWidget(QLabel("작품별 용어집 편집"))
        self.glossary_table = QTableWidget()
        self.glossary_table.setColumnCount(3)
        self.glossary_table.setHorizontalHeaderLabels(["원문", "번역", "후보"])
        self.glossary_table.setWordWrap(True)
        self.glossary_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.glossary_table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.glossary_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.glossary_table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.glossary_table.cellClicked.connect(self.handle_glossary_cell_clicked)
        self.glossary_table.itemChanged.connect(self.handle_glossary_item_changed)
        glossary_header = self.glossary_table.horizontalHeader()
        if glossary_header is not None:
            glossary_header.setSectionResizeMode(0, QHeaderView.Stretch)
            glossary_header.setSectionResizeMode(1, QHeaderView.Stretch)
            glossary_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.glossary_table.setColumnWidth(2, 110)
        layout.addWidget(self.glossary_table)

        layout.addWidget(QLabel("시트 컬럼 목록(추천 컬럼은 기본 체크)"))
        self.column_list = QListWidget()
        self.column_list.currentItemChanged.connect(self.handle_column_focus_changed)
        self.column_list.itemChanged.connect(self.handle_column_selection_changed)
        layout.addWidget(self.column_list)

        self.selection_stats_label = QLabel(
            "선택 컬럼 0개 | 총 글자 수 0자 (번역 엔진 사용량은 계정 설정 기준)"
        )
        layout.addWidget(self.selection_stats_label)

        layout.addWidget(QLabel("원본 시트 미리보기"))
        self.preview_table = QTableWidget()
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectColumns)
        horizontal_header = self.preview_table.horizontalHeader()
        if horizontal_header is not None:
            horizontal_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        vertical_header = self.preview_table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)
        layout.addWidget(self.preview_table)

        self.status_label = QLabel("파일을 선택한 뒤 '컬럼 분석'을 누르세요.")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("대기 중")
        layout.addWidget(self.progress_bar)

        layout.addWidget(QLabel("실시간 로그"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

        self.load_workbook_preview()
        self.load_glossary_editor()
        self._apply_provider_from_env()
        self._refresh_provider_limits()

    def choose_input_file(self) -> None:
        # [ANCHOR:UI_CHOOSE_INPUT]
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "엑셀 파일 선택",
            str(
                self.current_input_path.parent
                if self.current_input_path.exists()
                else Path.cwd()
            ),
            "Excel Files (*.xlsx)",
        )
        if not selected:
            return
        self.current_input_path = Path(selected)
        self.input_edit.setText(selected)
        self.load_workbook_preview()

    def choose_output_dir(self) -> None:
        # [ANCHOR:UI_CHOOSE_OUTPUT]
        selected = QFileDialog.getExistingDirectory(
            self,
            "출력 폴더 선택",
            self.output_edit.text() or str(Path.cwd()),
        )
        if selected:
            self.output_edit.setText(selected)

    def load_glossary_editor(self) -> None:
        # [ANCHOR:UI_GLOSSARY_LOAD]
        glossary_path = self._project_glossary_path()
        glossary = load_glossary(glossary_path)
        self.glossary_table.setRowCount(0)
        for source, target in sorted(glossary.items()):
            row_index = self.glossary_table.rowCount()
            self.glossary_table.insertRow(row_index)
            self.glossary_table.setItem(row_index, 0, QTableWidgetItem(source))
            self.glossary_table.setItem(row_index, 1, QTableWidgetItem(target))
            self._set_candidate_button(row_index, [])
        self._refresh_glossary_table_rows()
        self.status_label.setText(f"용어집 로드: {glossary_path}")

    def save_glossary_editor(self) -> None:
        # [ANCHOR:UI_GLOSSARY_SAVE]
        glossary_path = self._project_glossary_path()
        glossary = self._collect_glossary_rows()
        save_glossary(glossary_path, glossary)
        self.status_label.setText(f"용어집 저장: {glossary_path} ({len(glossary)}개)")

    def add_glossary_row(self) -> None:
        # [ANCHOR:UI_GLOSSARY_ADD_ROW]
        row_index = self.glossary_table.rowCount()
        self.glossary_table.insertRow(row_index)
        self.glossary_table.setItem(row_index, 0, QTableWidgetItem(""))
        self.glossary_table.setItem(row_index, 1, QTableWidgetItem(""))
        self._set_candidate_button(row_index, [])
        self._refresh_glossary_table_rows()
        self.glossary_table.setCurrentCell(row_index, 0)

    def remove_glossary_row(self) -> None:
        # [ANCHOR:UI_GLOSSARY_REMOVE_ROW]
        current_row = self.glossary_table.currentRow()
        if current_row < 0:
            return
        self.glossary_table.removeRow(current_row)
        self._refresh_glossary_table_rows()

    def handle_glossary_cell_clicked(self, row: int, column: int) -> None:
        # [ANCHOR:UI_GLOSSARY_CELL_CLICK]
        item = self.glossary_table.item(row, column)
        if item is None:
            item = QTableWidgetItem("")
            self.glossary_table.setItem(row, column, item)
        if column == 1:
            self._show_translation_candidates(row)
            return
        self.glossary_table.setCurrentItem(item)
        self.glossary_table.editItem(item)

    def handle_candidate_button_clicked(self) -> None:
        # [ANCHOR:UI_GLOSSARY_CANDIDATE_BUTTON_CLICK]
        sender = self.sender()
        if not isinstance(sender, QPushButton):
            return
        row = self.glossary_table.indexAt(sender.pos()).row()
        if row < 0:
            return
        self._show_translation_candidates(row)

    def handle_glossary_item_changed(self, item: QTableWidgetItem) -> None:
        # [ANCHOR:UI_GLOSSARY_ITEM_CHANGED]
        del item
        self._refresh_glossary_table_rows()

    def generate_glossary_candidates(self) -> None:
        # [ANCHOR:UI_GLOSSARY_GENERATE]
        input_path = Path(self.input_edit.text().strip())
        if not input_path.exists():
            QMessageBox.warning(self, "입력 오류", "입력 엑셀 파일을 찾을 수 없습니다.")
            return
        workbook = load_excel_workbook(input_path)
        context = build_sheet_context(workbook, self.get_selected_sheet_name())
        profiles = profile_columns(
            context.worksheet,
            header_row=context.header_row,
            data_start_row=context.data_start_row,
        )
        selected = select_translation_columns(profiles)
        self.glossary_table.setRowCount(0)
        self._populate_auto_glossary_candidates(context, selected, profiles)
        self.status_label.setText(
            f"자동 용어 생성 완료: {self.glossary_table.rowCount()}개"
        )

    def _collect_glossary_rows(self) -> dict[str, str]:
        # [ANCHOR:UI_GLOSSARY_COLLECT_ROWS]
        glossary: dict[str, str] = {}
        for row_index in range(self.glossary_table.rowCount()):
            source_item = self.glossary_table.item(row_index, 0)
            target_item = self.glossary_table.item(row_index, 1)
            source = source_item.text().strip() if source_item is not None else ""
            target = target_item.text().strip() if target_item is not None else ""
            if source and target:
                glossary[source] = target
        return glossary

    def _populate_auto_glossary_candidates(
        self, context, selected_profiles, all_profiles
    ) -> None:
        # [ANCHOR:UI_GLOSSARY_AUTO_POPULATE]
        if self.glossary_table.rowCount() > 0:
            return
        candidate_profiles = self._resolve_candidate_profiles_for_glossary(
            selected_profiles,
            all_profiles,
        )
        if not candidate_profiles:
            candidate_profiles = [
                profile for profile in all_profiles if int(profile.text_count) > 0
            ]
        selected_indexes = [int(profile.index) for profile in candidate_profiles]
        if not selected_indexes:
            return
        values: list[str] = []
        max_rows = min(context.worksheet.max_row, context.data_start_row + 1000)
        for row_index in range(context.data_start_row, max_rows + 1):
            for column_index in selected_indexes:
                cell_value = context.worksheet.cell(row_index, column_index).value
                if cell_value in (None, ""):
                    continue
                if isinstance(cell_value, (int, float)):
                    continue
                normalized = normalize_text(str(cell_value))
                if normalized:
                    values.append(normalized)
        candidates = extract_glossary_candidates(
            values,
            project_id=self._project_id(),
        )
        if not candidates:
            return
        suggested_translations = self._suggest_candidate_translations(candidates)
        for candidate in candidates:
            row_index = self.glossary_table.rowCount()
            self.glossary_table.insertRow(row_index)
            self.glossary_table.setItem(row_index, 0, QTableWidgetItem(candidate))
            options = suggested_translations.get(candidate, [])
            target_item = QTableWidgetItem(options[0] if options else "")
            target_item.setData(GLOSSARY_CANDIDATES_ROLE, options)
            self.glossary_table.setItem(row_index, 1, target_item)
            self._set_candidate_button(row_index, options)
        self._refresh_glossary_table_rows()

    def _resolve_candidate_profiles_for_glossary(self, selected_profiles, all_profiles):
        # [ANCHOR:UI_GLOSSARY_RESOLVE_CANDIDATE_PROFILES]
        checked_labels = self._checked_column_labels()
        if not checked_labels:
            return selected_profiles
        matched_profiles = [
            profile
            for profile in all_profiles
            if build_column_label(profile.index, profile.header) in checked_labels
        ]
        return matched_profiles if matched_profiles else selected_profiles

    def _checked_column_labels(self) -> set[str]:
        # [ANCHOR:UI_CHECKED_COLUMN_LABELS]
        labels: set[str] = set()
        for index in range(self.column_list.count()):
            item = self.column_list.item(index)
            if item is None:
                continue
            if item.checkState() != CHECKED_STATE:
                continue
            label = str(item.data(USER_ROLE) or "").strip()
            if label:
                labels.add(label)
        return labels

    def _set_candidate_button(self, row_index: int, options: list[str]) -> None:
        # [ANCHOR:UI_GLOSSARY_SET_CANDIDATE_BUTTON]
        button = QPushButton("후보 선택")
        if not options:
            button.setText("후보 없음")
            button.setEnabled(False)
        button.clicked.connect(self.handle_candidate_button_clicked)
        self.glossary_table.setCellWidget(row_index, 2, button)

    def _show_translation_candidates(self, row: int) -> None:
        # [ANCHOR:UI_GLOSSARY_SHOW_CANDIDATES]
        item = self.glossary_table.item(row, 1)
        if item is None:
            item = QTableWidgetItem("")
            self.glossary_table.setItem(row, 1, item)
        raw_options = item.data(GLOSSARY_CANDIDATES_ROLE)
        options: list[str] = []
        if isinstance(raw_options, list):
            options = [
                str(value).strip() for value in raw_options if str(value).strip()
            ]
        if not options:
            self.glossary_table.setCurrentItem(item)
            self.glossary_table.editItem(item)
            return
        current_value = item.text().strip()
        if current_value and current_value not in options:
            options.insert(0, current_value)
        selected, accepted = QInputDialog.getItem(
            self,
            "번역 후보 선택",
            "후보 선택 또는 직접 입력",
            options,
            0,
            True,
        )
        if accepted:
            item.setText(str(selected).strip())

    def _refresh_glossary_table_rows(self) -> None:
        # [ANCHOR:UI_GLOSSARY_REFRESH_ROWS]
        self.glossary_table.resizeRowsToContents()

    def _suggest_candidate_translations(
        self, candidates: list[str]
    ) -> dict[str, list[str]]:
        # [ANCHOR:UI_GLOSSARY_SUGGEST_TRANSLATIONS]
        suggestions: dict[str, list[str]] = {}
        glossary_paths = [self._project_glossary_path()]
        if self._project_id():
            glossary_paths = [
                self._global_glossary_path(),
                self._project_glossary_path(),
            ]
        existing = load_glossary_layers(glossary_paths)
        existing_lower = {source.lower(): target for source, target in existing.items()}
        unresolved: list[str] = []
        for candidate in candidates:
            unresolved.append(candidate)

        translated = self._translate_terms_without_llm(unresolved)
        translated_by_source = {
            source: target for source, target in zip(unresolved, translated)
        }
        existing_sources = list(existing.keys())
        for candidate in candidates:
            options: list[str] = []
            seen: set[str] = set()

            exact = existing.get(candidate)
            lowered = existing_lower.get(candidate.lower())
            for value in (exact, lowered):
                normalized = str(value or "").strip()
                key = normalized.lower()
                if not normalized or key in seen:
                    continue
                options.append(normalized)
                seen.add(key)

            for similar_source in difflib.get_close_matches(
                candidate,
                existing_sources,
                n=3,
                cutoff=0.6,
            ):
                normalized = existing.get(similar_source, "").strip()
                key = normalized.lower()
                if not normalized or key in seen:
                    continue
                options.append(normalized)
                seen.add(key)

            offline = translated_by_source.get(candidate, "").strip()
            offline_key = offline.lower()
            if offline and offline_key not in seen:
                options.append(offline)
                seen.add(offline_key)

            for variant in self._build_translation_variants(offline):
                key = variant.lower()
                if not variant or key in seen:
                    continue
                options.append(variant)
                seen.add(key)

            raw_source = candidate.strip()
            source_key = raw_source.lower()
            if raw_source and source_key not in seen:
                options.append(raw_source)
                seen.add(source_key)

            if not options:
                options.append(candidate)
            suggestions[candidate] = options[:3]
        return suggestions

    def _build_translation_variants(self, text: str) -> list[str]:
        # [ANCHOR:UI_GLOSSARY_BUILD_VARIANTS]
        base = text.strip()
        if not base:
            return []
        substitutions = {
            "뷰": ["화면", "창"],
            "움직임": ["모션"],
            "타이밍": ["시점"],
            "컴포지트": ["합성"],
            "익스포트": ["내보내기"],
            "클린업": ["정리"],
        }
        variants: list[str] = []
        for source, targets in substitutions.items():
            if source not in base:
                continue
            for target in targets:
                variants.append(base.replace(source, target, 1).strip())
        return variants

    def _translate_terms_without_llm(self, terms: list[str]) -> list[str]:
        # [ANCHOR:UI_GLOSSARY_TRANSLATE_TERMS_OFFLINE]
        if not terms:
            return []
        if importlib_util.find_spec("argostranslate") is None:
            return self._translate_terms_rule_based(terms)
        try:
            from argostranslate import package, translate  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001
            return self._translate_terms_rule_based(terms)

        languages = translate.get_installed_languages()
        source_language = next((lang for lang in languages if lang.code == "en"), None)
        target_language = next((lang for lang in languages if lang.code == "ko"), None)
        if source_language is None or target_language is None:
            return self._translate_terms_rule_based(terms)

        translation = source_language.get_translation(target_language)
        if translation is None:
            package_index = package.get_available_packages()
            install_target = next(
                (
                    item
                    for item in package_index
                    if item.from_code == "en" and item.to_code == "ko"
                ),
                None,
            )
            if install_target is None:
                return self._translate_terms_rule_based(terms)
            try:
                package.install_from_path(install_target.download())
            except Exception:  # noqa: BLE001
                return self._translate_terms_rule_based(terms)
            languages = translate.get_installed_languages()
            source_language = next(
                (lang for lang in languages if lang.code == "en"), None
            )
            target_language = next(
                (lang for lang in languages if lang.code == "ko"), None
            )
            if source_language is None or target_language is None:
                return self._translate_terms_rule_based(terms)
            translation = source_language.get_translation(target_language)
            if translation is None:
                return self._translate_terms_rule_based(terms)

        try:
            translated = [translation.translate(term) for term in terms]
            fallback = self._translate_terms_rule_based(terms)
            merged: list[str] = []
            for index, original in enumerate(terms):
                value = translated[index].strip()
                if value:
                    merged.append(value)
                    continue
                fallback_value = fallback[index].strip()
                merged.append(fallback_value if fallback_value else original)
            return merged
        except Exception:  # noqa: BLE001
            return self._translate_terms_rule_based(terms)

    def _translate_terms_rule_based(self, terms: list[str]) -> list[str]:
        # [ANCHOR:UI_GLOSSARY_TRANSLATE_TERMS_RULE_BASED]
        dictionary = {
            "node": "노드",
            "view": "뷰",
            "camera": "카메라",
            "movement": "움직임",
            "timing": "타이밍",
            "acting": "액팅",
            "composite": "컴포지트",
            "scene": "씬",
            "shot": "샷",
            "background": "배경",
            "animation": "애니메이션",
            "effect": "이펙트",
            "effects": "이펙트",
            "sfx": "효과음",
            "bg": "배경",
            "fx": "효과",
            "render": "렌더",
            "export": "익스포트",
            "cleanup": "클린업",
            "layer": "레이어",
            "peg": "페그",
            "cutter": "커터",
        }
        translated_terms: list[str] = []
        for term in terms:
            parts = re.findall(r"[A-Za-z]+|[^A-Za-z]+", term)
            translated_parts: list[str] = []
            for part in parts:
                if re.fullmatch(r"[A-Za-z]+", part):
                    replacement = dictionary.get(part.lower())
                    translated_parts.append(
                        str(replacement) if replacement is not None else str(part)
                    )
                else:
                    translated_parts.append(str(part))
            combined = "".join(translated_parts).strip()
            translated_terms.append(combined if combined else term)
        return translated_terms

    def _translate_terms_with_provider(self, terms: list[str]) -> list[str]:
        # [ANCHOR:UI_GLOSSARY_TRANSLATE_TERMS]
        if not terms:
            return []
        provider = self._current_provider()
        if provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY", "").strip()
            if not api_key:
                return [""] * len(terms)
            base_url = os.environ.get(
                "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com"
            )
            client = GeminiClient(
                api_key=api_key,
                model=self._selected_gemini_model() or "gemini-2.5-flash",
                base_url=base_url,
            )
            try:
                return client.translate_batch(
                    terms,
                    source_lang="EN",
                    target_lang="KO",
                )
            except Exception:  # noqa: BLE001
                return [""] * len(terms)

        api_key = os.environ.get("DEEPL_API_KEY", "").strip()
        if not api_key:
            return [""] * len(terms)
        base_url = os.environ.get("DEEPL_BASE_URL", "https://api-free.deepl.com")
        client = DeepLClient(api_key=api_key, base_url=base_url)
        try:
            return client.translate_batch(
                terms,
                source_lang="EN",
                target_lang="KO",
            )
        except Exception:  # noqa: BLE001
            return [""] * len(terms)

    def _project_glossary_path(self) -> Path:
        # [ANCHOR:UI_PROJECT_GLOSSARY_PATH]
        project_id = self.project_id_edit.text().strip()
        if not project_id:
            return Path("glossary.tsv")
        return PROJECT_GLOSSARY_ROOT / project_id / "glossary.tsv"

    @staticmethod
    def _global_glossary_path() -> Path:
        # [ANCHOR:UI_GLOBAL_GLOSSARY_PATH]
        return Path("glossary/global.tsv")

    def _project_id(self) -> str:
        return self.project_id_edit.text().strip()

    def _cache_path(self) -> Path:
        # [ANCHOR:UI_CACHE_PATH]
        project_id = self._project_id()
        if not project_id:
            return Path(".cache/translations.sqlite3")
        return Path(f".cache/translations_{project_id}.sqlite3")

    def _infer_project_id_from_input(self, input_path: Path) -> None:
        # [ANCHOR:UI_INFER_PROJECT_ID]
        if self._project_id():
            return
        match = re.search(r"([A-Za-z]{2}\d{4})", input_path.stem)
        if match is None:
            return
        self.project_id_edit.setText(match.group(1).upper())

    def load_workbook_preview(self) -> None:
        # [ANCHOR:UI_LOAD_PREVIEW]
        input_path = Path(self.input_edit.text().strip())
        if not input_path.exists():
            self.status_label.setText("입력 파일을 찾을 수 없습니다.")
            self.column_list.clear()
            self._update_preserve_original_label(input_path=input_path, sheet_name=None)
            self._update_selection_stats_label()
            return

        self._infer_project_id_from_input(input_path)
        self.load_glossary_editor()
        workbook = load_excel_workbook(input_path)
        self._refresh_provider_limits()
        self._populate_sheet_names(workbook.sheetnames)
        sheet_name = self.get_selected_sheet_name()
        self._update_preserve_original_label(
            input_path=input_path, sheet_name=sheet_name
        )
        context = build_sheet_context(workbook, sheet_name)
        profiles = profile_columns(
            context.worksheet,
            header_row=context.header_row,
            data_start_row=context.data_start_row,
        )
        selected = select_translation_columns(profiles)
        self._populate_auto_glossary_candidates(context, selected, profiles)
        recommended_labels = {
            build_column_label(profile.index, profile.header) for profile in selected
        }
        self.column_suggestions = [
            ColumnSuggestion(
                index=profile.index,
                header=profile.header,
                label=build_column_label(profile.index, profile.header),
                score=profile.score,
                text_count=profile.text_count,
                character_count=profile.character_count,
            )
            for profile in profiles
        ]
        self.column_list.clear()
        for suggestion in self.column_suggestions:
            item = QListWidgetItem(
                f"{suggestion.label}  |  score={suggestion.score:.1f}  |  rows={suggestion.text_count}"
            )
            item.setFlags(item.flags() | ITEM_IS_USER_CHECKABLE)
            item.setCheckState(
                CHECKED_STATE
                if suggestion.label in recommended_labels
                else Qt.CheckState.Unchecked
            )
            item.setData(USER_ROLE, suggestion.label)
            if suggestion.label in recommended_labels:
                item.setBackground(RECOMMENDED_BG)
            self.column_list.addItem(item)
        preview_headers, preview_rows = build_sheet_preview(
            context.worksheet,
            header_row=context.header_row,
        )
        self._populate_preview_table(preview_headers, preview_rows, recommended_labels)
        current_item = self.column_list.currentItem()
        if current_item is not None:
            self.focus_preview_column(str(current_item.data(USER_ROLE)))
        self._update_selection_stats_label()
        self.status_label.setText(
            f"헤더행 {context.header_row} 감지, 전체 컬럼 {len(profiles)}개 / 추천 {len(recommended_labels)}개"
        )

    def handle_sheet_changed(self) -> None:
        # [ANCHOR:UI_HANDLE_SHEET_CHANGED]
        if self.available_sheet_names:
            self.load_workbook_preview()

    def handle_provider_changed(self) -> None:
        self._refresh_provider_limits()
        self._update_selection_stats_label()

    def handle_gemini_model_changed(self) -> None:
        self._update_selection_stats_label()

    def handle_column_focus_changed(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        # [ANCHOR:UI_HANDLE_COLUMN_FOCUS_CHANGED]
        del previous
        if current is None:
            return
        self.focus_preview_column(str(current.data(USER_ROLE)))

    def handle_column_selection_changed(self, item: QListWidgetItem) -> None:
        del item
        self._update_selection_stats_label()

    def focus_preview_column(self, column_label: str) -> None:
        # [ANCHOR:UI_FOCUS_PREVIEW_COLUMN]
        column_index = self.preview_column_index_by_label.get(column_label)
        if column_index is None:
            return
        target_item = self.preview_table.item(0, column_index)
        if target_item is None:
            target_item = QTableWidgetItem("")
            self.preview_table.setItem(0, column_index, target_item)
        self.preview_table.setCurrentItem(target_item)
        self.preview_table.selectColumn(column_index)
        self.preview_table.scrollToItem(target_item, QAbstractItemView.PositionAtCenter)

    def run_from_ui(self) -> None:
        # [ANCHOR:UI_RUN_PIPELINE]
        input_path = Path(self.input_edit.text().strip())
        if not input_path.exists():
            QMessageBox.warning(self, "입력 오류", "입력 엑셀 파일을 찾을 수 없습니다.")
            return

        selected_columns: list[str] = []
        for index in range(self.column_list.count()):
            item = self.column_list.item(index)
            if item is None:
                continue
            if item.checkState() == CHECKED_STATE:
                selected_columns.append(str(item.data(USER_ROLE)))
        if not selected_columns:
            QMessageBox.warning(self, "컬럼 선택", "최소 하나의 컬럼을 선택하세요.")
            return

        config = build_config(
            input_path=input_path,
            output_dir=Path(self.output_edit.text().strip() or "output"),
            sheet_name=self.get_selected_sheet_name(),
            selected_columns=selected_columns,
            preserve_original_sheet=self.preserve_original_checkbox.isChecked(),
            mapped_cell_mode=str(self.mapped_cell_mode_combo.currentData()),
            glossary_path=self._project_glossary_path(),
            exclude_patterns_path=Path("exclude_patterns.yaml"),
            source_lang="EN",
            target_lang="KO",
            provider=self._current_provider(),
            gemini_model=self._selected_gemini_model(),
            cache_path=self._cache_path(),
            env_file=Path(".env"),
            global_glossary_path=(
                self._global_glossary_path() if self._project_id() else None
            ),
            project_id=self._project_id(),
        )

        self.run_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.status_label.setText("실행 중...")
        self.log_view.clear()
        self.log_view.appendPlainText("실행 시작: 백그라운드 파이프라인을 준비합니다.")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("처리 중...")
        worker_thread = QThread(self)
        worker = PipelineWorker(config)
        self.worker_thread = worker_thread
        self.worker = worker
        worker.moveToThread(worker_thread)
        worker_thread.started.connect(worker.run)
        worker.finished.connect(self.handle_run_finished)
        worker.failed.connect(self.handle_run_failed)
        worker.progress.connect(self.handle_run_progress)
        worker.progress_value.connect(self.handle_run_progress_value)
        worker.finished.connect(worker_thread.quit)
        worker.failed.connect(worker_thread.quit)
        worker_thread.finished.connect(self.cleanup_worker)
        worker_thread.start()

    def handle_run_finished(self, result: PipelineResult) -> None:
        # [ANCHOR:UI_RUN_FINISHED]
        self.run_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self._refresh_provider_limits()
        self._update_selection_stats_label()
        preview_note = "\n프리뷰 모드로 실행됨" if result.preview_mode else ""
        self.status_label.setText("실행 완료")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat("완료 100%")
        QMessageBox.information(
            self,
            "완료",
            "\n".join(
                [
                    f"Translated: {result.translated_path}",
                    f"SourceMapped: {result.source_mapped_path}",
                    f"Audit: {result.audit_path}",
                    f"Usage: {result.usage_path}",
                    preview_note.strip(),
                ]
            ).strip(),
        )

    def handle_run_failed(self, message: str) -> None:
        # [ANCHOR:UI_RUN_FAILED]
        self.run_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self.status_label.setText("실행 실패")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("실패")
        QMessageBox.critical(self, "실행 실패", message)

    def handle_run_progress(self, message: str) -> None:
        self.log_view.appendPlainText(message)

    def handle_run_progress_value(self, value: int) -> None:
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"진행률 {value}%")

    def cleanup_worker(self) -> None:
        # [ANCHOR:UI_WORKER_CLEANUP]
        self.worker = None
        self.worker_thread = None

    def get_selected_sheet_name(self) -> str | None:
        # [ANCHOR:UI_GET_SELECTED_SHEET]
        current_text = self.sheet_combo.currentText().strip()
        return current_text or None

    def _populate_sheet_names(self, sheet_names: list[str]) -> None:
        # [ANCHOR:UI_POPULATE_SHEETS]
        if self.available_sheet_names == sheet_names:
            return
        current_selection = self.sheet_combo.currentText()
        self.available_sheet_names = list(sheet_names)
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(sheet_names)
        if current_selection and current_selection in sheet_names:
            self.sheet_combo.setCurrentText(current_selection)
        self.sheet_combo.blockSignals(False)

    def _populate_preview_table(
        self,
        headers: list[str],
        rows: list[list[str]],
        recommended_labels: set[str],
    ) -> None:
        # [ANCHOR:UI_POPULATE_PREVIEW_TABLE]
        self.preview_table.clear()
        self.preview_table.setColumnCount(len(headers))
        self.preview_table.setRowCount(len(rows))
        self.preview_table.setHorizontalHeaderLabels(headers)
        self.preview_column_index_by_label = {
            header_label: column_index
            for column_index, header_label in enumerate(headers)
        }

        for column_index, header_label in enumerate(headers):
            header_item = self.preview_table.horizontalHeaderItem(column_index)
            if header_item is None:
                continue
            if header_label in recommended_labels:
                header_item.setBackground(RECOMMENDED_BG)

        for row_index, row_values in enumerate(rows):
            for column_index, value in enumerate(row_values):
                item = QTableWidgetItem(value)
                self.preview_table.setItem(row_index, column_index, item)

    def _update_selection_stats_label(self) -> None:
        selected_column_count = 0
        selected_character_count = 0
        suggestion_count = len(self.column_suggestions)
        for index in range(self.column_list.count()):
            item = self.column_list.item(index)
            if item is None:
                continue
            if item.checkState() != CHECKED_STATE:
                continue
            selected_column_count += 1
            if index < suggestion_count:
                selected_character_count += self.column_suggestions[
                    index
                ].character_count

        limit_text = self._build_limit_text()

        self.selection_stats_label.setText(
            f"선택 컬럼 {selected_column_count}개 | 총 글자 수 {selected_character_count:,}자 ({limit_text})"
        )

    def _refresh_deepl_character_limit(self) -> None:
        load_env_file(Path(".env"))
        api_key = os.environ.get("DEEPL_API_KEY", "").strip()
        if not api_key:
            self.deepl_character_count = None
            self.deepl_character_limit = None
            return

        base_url = os.environ.get("DEEPL_BASE_URL", "https://api-free.deepl.com")
        try:
            usage = DeepLClient(api_key=api_key, base_url=base_url).usage()
            self.deepl_character_count = usage.character_count
            self.deepl_character_limit = usage.character_limit
        except Exception:  # noqa: BLE001
            self.deepl_character_count = None
            self.deepl_character_limit = None

    def _refresh_provider_limits(self) -> None:
        provider = self._current_provider()
        if provider == "gemini":
            self._refresh_gemini_models()
            self.deepl_character_count = None
            self.deepl_character_limit = None
            return
        self.model_combo.setEnabled(False)
        self._refresh_deepl_character_limit()

    def _refresh_gemini_models(self) -> None:
        load_env_file(Path(".env"))
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        base_url = os.environ.get(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com"
        )
        configured_model = os.environ.get("GEMINI_MODEL", "").strip()
        current_model = self._selected_gemini_model() or configured_model

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.gemini_models_by_id = {}

        if not api_key:
            self.model_combo.addItem("GEMINI_API_KEY 없음", "")
            self.model_combo.setEnabled(False)
            self.model_combo.blockSignals(False)
            return

        try:
            client = GeminiClient(
                api_key=api_key,
                model=configured_model or "gemini-2.5-flash",
                base_url=base_url,
            )
            models = client.list_models()
        except Exception:  # noqa: BLE001
            models = []

        known_models = self._known_gemini_models()
        preferred_models = self._preferred_gemini_models(
            configured_model=configured_model,
            current_model=current_model,
            known_models=known_models,
        )

        if not models:
            fallback_model = configured_model or "gemini-2.5-flash"
            self.model_combo.addItem(fallback_model, fallback_model)
            for model_id in preferred_models:
                if self.model_combo.findData(model_id) < 0:
                    self.model_combo.addItem(model_id, model_id)
            self.model_combo.setEnabled(True)
            self.model_combo.blockSignals(False)
            return

        available_models = {model.model_id: model for model in models}
        visible_model_ids = [
            model_id for model_id in preferred_models if model_id in available_models
        ]
        if not visible_model_ids:
            visible_model_ids = [models[0].model_id]

        self.gemini_models_by_id = {
            model_id: available_models[model_id] for model_id in visible_model_ids
        }
        for model_id in visible_model_ids:
            self.model_combo.addItem(model_id, model_id)
        for model_id in preferred_models:
            if self.model_combo.findData(model_id) < 0:
                self.model_combo.addItem(model_id, model_id)

        target_model = (
            current_model
            if current_model in self.gemini_models_by_id
            else models[0].model_id
        )
        target_index = self.model_combo.findData(target_model)
        if target_index >= 0:
            self.model_combo.setCurrentIndex(target_index)
        elif target_model:
            self.model_combo.setEditText(target_model)

        self.model_combo.setEnabled(True)
        self.model_combo.blockSignals(False)

    @staticmethod
    def _preferred_gemini_models(
        *, configured_model: str, current_model: str, known_models: list[str]
    ) -> list[str]:
        ordered: list[str] = []
        for model_id in known_models:
            if model_id and model_id not in ordered:
                ordered.append(model_id)
        for model_id in (configured_model, current_model):
            if model_id and model_id not in ordered:
                ordered.append(model_id)
        return ordered

    def _known_gemini_models(self) -> list[str]:
        configured_models = os.environ.get("GEMINI_MODEL_CANDIDATES", "").strip()
        if not configured_models:
            return list(KNOWN_GEMINI_MODELS)

        models: list[str] = []
        for model_id in configured_models.split(","):
            normalized = model_id.strip()
            if not normalized:
                continue
            if normalized in models:
                continue
            models.append(normalized)
        if models:
            return models
        return list(KNOWN_GEMINI_MODELS)

    def _build_limit_text(self) -> str:
        provider = self._current_provider()
        if provider == "gemini":
            model_id = self._selected_gemini_model()
            model = self.gemini_models_by_id.get(model_id)
            if model is None:
                return "Gemini 제한 정보는 모델/키 설정 후 표시"
            return (
                f"Gemini {model.model_id} 제한 입력 {model.input_token_limit:,}tok / "
                f"출력 {model.output_token_limit:,}tok"
            )

        if (
            self.deepl_character_count is not None
            and self.deepl_character_limit is not None
            and self.deepl_character_limit > 0
        ):
            remaining_characters = max(
                self.deepl_character_limit - self.deepl_character_count, 0
            )
            return (
                f"DeepL 사용량 {self.deepl_character_count:,}/{self.deepl_character_limit:,}자 "
                f"(남은 {remaining_characters:,}자)"
            )
        return "DeepL 사용량은 계정 설정 기준"

    def _current_provider(self) -> str:
        data = self.provider_combo.currentData()
        return normalize_provider(str(data or "gemini"))

    def _selected_gemini_model(self) -> str:
        data = self.model_combo.currentData()
        if data:
            return str(data)
        return self.model_combo.currentText().strip()

    def _update_preserve_original_label(
        self, *, input_path: Path, sheet_name: str | None
    ) -> None:
        output_name = f"{input_path.stem}_KO.xlsx"
        if not input_path.exists():
            self.preserve_original_checkbox.setText(
                "번역본(_KO.xlsx)에 현재 시트 원문 백업 시트 보존"
            )
            return

        display_sheet_name = sheet_name or input_path.stem
        self.preserve_original_checkbox.setText(
            f"{output_name}에 '{display_sheet_name}_ORIGINAL' 백업 시트 보존"
        )

    def _apply_provider_from_env(self) -> None:
        load_env_file(Path(".env"))
        provider = normalize_provider(os.environ.get("TRANSLATION_PROVIDER", "gemini"))
        index = self.provider_combo.findData(provider)
        if index >= 0:
            self.provider_combo.setCurrentIndex(index)


def launch_ui() -> int:
    # [ANCHOR:UI_APP_LAUNCH]
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()
