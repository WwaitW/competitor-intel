"""
search_cache.py — 搜索结果 SQLite 缓存（TTL 12 小时）

解决的问题：
  同一竞品短时间多次分析时，每次都重新调用 Tavily/DuckDuckGo，
  既浪费 API 额度，搜索结果也不稳定（相同查询可能返回不同顺序）。

设计决策：
  缓存原始结果（ResultFilter/DiversityFilter 过滤之前）
  → 同一查询不同 require_keyword / max_results 的调用都能命中同一缓存条目
  → 过滤仍在调用侧执行，结果语义正确

Cache Key 组成：
  hash(query + search_type + days + include_domains_sorted)
  不含 require_keyword / max_results（这两个是后处理参数）

TTL：12 小时（43200 秒）
清理策略：惰性淘汰（每次写入时批量删除最多 50 条过期记录，无后台线程）
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta

import config

CACHE_TTL_SECONDS = 43_200  # 12 小时


class SearchCache:

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        self._init_table()

    def _init_table(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    key          TEXT PRIMARY KEY,
                    query        TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    cached_at    TEXT NOT NULL
                )
            """)
            conn.commit()

    # ── Key 生成 ─────────────────────────────────────────────────────

    @staticmethod
    def make_key(
        query: str,
        search_type: str,                   # "general" | "news"
        days: int | None,
        include_domains: list[str] | None,
    ) -> str:
        parts = {
            "q":   query.lower().strip(),
            "t":   search_type,
            "d":   days,
            "dom": sorted(include_domains) if include_domains else None,
        }
        raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    # ── 读写接口 ─────────────────────────────────────────────────────

    def get(self, key: str) -> list[dict] | None:
        """返回未过期的缓存结果；未命中或已过期返回 None"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT results_json, cached_at FROM search_cache WHERE key = ?",
                (key,),
            ).fetchone()

        if not row:
            return None

        results_json, cached_at_str = row
        cached_at = datetime.fromisoformat(cached_at_str)
        if datetime.now() - cached_at > timedelta(seconds=CACHE_TTL_SECONDS):
            return None  # 惰性淘汰：标记过期，不立即删除

        try:
            return json.loads(results_json)
        except Exception:
            return None

    def set(self, key: str, query: str, results: list[dict]):
        """写入缓存并惰性清理过期记录（最多清 50 条）"""
        if not results:
            return  # 不缓存空结果，避免错误传播

        now = datetime.now().isoformat()
        expiry = (datetime.now() - timedelta(seconds=CACHE_TTL_SECONDS)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO search_cache "
                "(key, query, results_json, cached_at) VALUES (?, ?, ?, ?)",
                (key, query, json.dumps(results, ensure_ascii=False), now),
            )
            # 惰性清理：每次写入顺带删除过期条目（限量 500，防止表长期膨胀）
            conn.execute(
                "DELETE FROM search_cache WHERE key IN "
                "(SELECT key FROM search_cache WHERE cached_at < ? LIMIT 500)",
                (expiry,),
            )
            conn.commit()

    # ── 统计接口（供 UI 展示）────────────────────────────────────────

    def stats(self) -> dict:
        """返回缓存统计：{total, valid, expired, oldest_valid}"""
        expiry = (datetime.now() - timedelta(seconds=CACHE_TTL_SECONDS)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM search_cache"
            ).fetchone()[0]
            valid = conn.execute(
                "SELECT COUNT(*) FROM search_cache WHERE cached_at >= ?",
                (expiry,),
            ).fetchone()[0]
            oldest_row = conn.execute(
                "SELECT query, cached_at FROM search_cache WHERE cached_at >= ? "
                "ORDER BY cached_at ASC LIMIT 1",
                (expiry,),
            ).fetchone()

        oldest_at = oldest_row[1][:16] if oldest_row else None  # YYYY-MM-DDTHH:MM
        return {
            "total":   total,
            "valid":   valid,
            "expired": total - valid,
            "oldest_valid_at": oldest_at,
        }

    def clear(self):
        """清空全部缓存（用于 UI 手动清除按钮）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM search_cache")
            conn.commit()
