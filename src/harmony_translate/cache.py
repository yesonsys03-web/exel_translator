from __future__ import annotations

from pathlib import Path
import sqlite3


class TranslationCache:
    # [ANCHOR:CACHE_SQLITE_STORE]
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS translations (source TEXT PRIMARY KEY, target TEXT NOT NULL)"
        )
        self.connection.commit()

    def get_many(self, texts: list[str]) -> dict[str, str]:
        if not texts:
            return {}
        placeholders = ", ".join("?" for _ in texts)
        cursor = self.connection.execute(
            f"SELECT source, target FROM translations WHERE source IN ({placeholders})",
            texts,
        )
        return {source: target for source, target in cursor.fetchall()}

    def set_many(self, pairs: dict[str, str]) -> None:
        if not pairs:
            return
        self.connection.executemany(
            "INSERT OR REPLACE INTO translations(source, target) VALUES(?, ?)",
            list(pairs.items()),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
