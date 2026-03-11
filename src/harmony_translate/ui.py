from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys

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
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QAbstractItemView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from harmony_translate.cli import DEFAULT_INPUT_PATH, build_config
from harmony_translate.config import load_env_file
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
from harmony_translate.pipeline import PipelineResult, run_pipeline
from harmony_translate.translator_deepl import DeepLClient
from harmony_translate.translator_gemini import GeminiClient, GeminiModelInfo


ITEM_IS_USER_CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable
CHECKED_STATE = Qt.CheckState.Checked
USER_ROLE = Qt.ItemDataRole.UserRole
RECOMMENDED_BG = Qt.GlobalColor.yellow
KNOWN_GEMINI_MODELS = [
    "gemini-3-pro",
    "gemini-3-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]


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

    def __init__(self, config) -> None:
        super().__init__()
        self.config = config

    def run(self) -> None:
        def _emit_progress(message: str) -> None:
            self.progress.emit(message)
            print(message)

        try:
            result = run_pipeline(self.config, log_callback=_emit_progress)
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

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("DeepL", "deepl")
        self.provider_combo.addItem("Google AI Studio (Gemini)", "gemini")
        self.provider_combo.currentIndexChanged.connect(self.handle_provider_changed)
        form_layout.addWidget(QLabel("번역 엔진"), 3, 0)
        form_layout.addWidget(self.provider_combo, 3, 1, 1, 2)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.currentIndexChanged.connect(self.handle_gemini_model_changed)
        form_layout.addWidget(QLabel("Gemini 모델"), 4, 0)
        form_layout.addWidget(self.model_combo, 4, 1, 1, 2)

        button_row = QHBoxLayout()
        layout.addLayout(button_row)
        self.load_button = QPushButton("컬럼 분석")
        self.load_button.clicked.connect(self.load_workbook_preview)
        button_row.addWidget(self.load_button)
        self.run_button = QPushButton("실행")
        self.run_button.clicked.connect(self.run_from_ui)
        button_row.addWidget(self.run_button)

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

        layout.addWidget(QLabel("실시간 로그"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

        self.load_workbook_preview()
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

    def load_workbook_preview(self) -> None:
        # [ANCHOR:UI_LOAD_PREVIEW]
        input_path = Path(self.input_edit.text().strip())
        if not input_path.exists():
            self.status_label.setText("입력 파일을 찾을 수 없습니다.")
            self.column_list.clear()
            self._update_selection_stats_label()
            return

        workbook = load_excel_workbook(input_path)
        self._refresh_provider_limits()
        self._populate_sheet_names(workbook.sheetnames)
        sheet_name = self.get_selected_sheet_name()
        context = build_sheet_context(workbook, sheet_name)
        profiles = profile_columns(
            context.worksheet,
            header_row=context.header_row,
            data_start_row=context.data_start_row,
        )
        selected = select_translation_columns(profiles)
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
            glossary_path=Path("glossary.tsv"),
            exclude_patterns_path=Path("exclude_patterns.yaml"),
            source_lang="EN",
            target_lang="KO",
            provider=self._current_provider(),
            gemini_model=self._selected_gemini_model(),
            cache_path=Path(".cache/translations.sqlite3"),
            env_file=Path(".env"),
        )

        self.run_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.status_label.setText("실행 중...")
        self.log_view.clear()
        worker_thread = QThread(self)
        worker = PipelineWorker(config)
        self.worker_thread = worker_thread
        self.worker = worker
        worker.moveToThread(worker_thread)
        worker_thread.started.connect(worker.run)
        worker.finished.connect(self.handle_run_finished)
        worker.failed.connect(self.handle_run_failed)
        worker.progress.connect(self.handle_run_progress)
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
        QMessageBox.critical(self, "실행 실패", message)

    def handle_run_progress(self, message: str) -> None:
        self.log_view.appendPlainText(message)

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
                model=configured_model or "gemini-3-flash",
                base_url=base_url,
            )
            models = client.list_models()
        except Exception:  # noqa: BLE001
            models = []

        if not models:
            fallback_model = configured_model or "gemini-3-flash"
            self.model_combo.addItem(fallback_model, fallback_model)
            for model_id in KNOWN_GEMINI_MODELS:
                if self.model_combo.findData(model_id) < 0:
                    self.model_combo.addItem(model_id, model_id)
            self.model_combo.setEnabled(True)
            self.model_combo.blockSignals(False)
            return

        self.gemini_models_by_id = {model.model_id: model for model in models}
        for model in models:
            label = f"{model.model_id}"
            self.model_combo.addItem(label, model.model_id)
        for model_id in KNOWN_GEMINI_MODELS:
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
        return str(data or "deepl")

    def _selected_gemini_model(self) -> str:
        data = self.model_combo.currentData()
        if data:
            return str(data)
        return self.model_combo.currentText().strip()

    def _apply_provider_from_env(self) -> None:
        load_env_file(Path(".env"))
        provider = os.environ.get("TRANSLATION_PROVIDER", "deepl").strip().lower()
        index = self.provider_combo.findData(provider)
        if index >= 0:
            self.provider_combo.setCurrentIndex(index)


def launch_ui() -> int:
    # [ANCHOR:UI_APP_LAUNCH]
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()
