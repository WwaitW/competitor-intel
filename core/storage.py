"""
storage.py — SQLite 历史记录存储
"""
import sqlite3
import json
from datetime import datetime
import config


class Storage:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor TEXT NOT NULL,
                    our_product TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    report_md TEXT,
                    meta_json TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.commit()

    def save(self, competitor: str, our_product: str, model: str, report_md: str, meta: dict) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO analyses (competitor, our_product, model, report_md, meta_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (competitor, our_product, model, report_md, json.dumps(meta, ensure_ascii=False)),
            )
            conn.commit()
            return cursor.lastrowid

    def list_recent(self, limit: int = 20) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, competitor, our_product, model, created_at, meta_json FROM analyses ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get(self, record_id: int) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM analyses WHERE id = ?", (record_id,)
            ).fetchone()
        if not row:
            return None
        record = dict(row)
        # 自动反序列化 meta_json，避免调用方因 JSON 损坏而崩溃
        try:
            record["meta_json"] = json.loads(record.get("meta_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            record["meta_json"] = {}
        return record

    def delete(self, record_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM analyses WHERE id = ?", (record_id,))
            conn.commit()
