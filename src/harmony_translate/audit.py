from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from openpyxl import Workbook


@dataclass
class AuditEntry:
    sheet_name: str
    row_index: int
    source_header: str
    source_text: str
    translated_text: str
    cache_hit: bool
    skipped: bool
    reason: str


def export_audit(entries: list[AuditEntry], output_path: Path) -> None:
    # [ANCHOR:AUDIT_EXPORT_REPORT]
    workbook = Workbook()
    worksheet = workbook.active
    if worksheet is None:
        raise RuntimeError("Failed to create audit worksheet")
    worksheet.title = "Audit"
    worksheet.append(
        [
            "sheet_name",
            "row_index",
            "source_header",
            "source_text",
            "translated_text",
            "cache_hit",
            "skipped",
            "reason",
        ]
    )
    for entry in entries:
        worksheet.append(
            [
                entry.sheet_name,
                entry.row_index,
                entry.source_header,
                entry.source_text,
                entry.translated_text,
                entry.cache_hit,
                entry.skipped,
                entry.reason,
            ]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def export_usage_report(payload: dict[str, object], output_path: Path) -> None:
    # [ANCHOR:AUDIT_EXPORT_USAGE]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
