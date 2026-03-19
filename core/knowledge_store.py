"""
knowledge_store.py — 竞品知识库（P3.2 GraphRAG-lite + #29 人工编辑）

基于 SQLite 的竞品事实持久化存储，与现有 analyses 表共享同一数据库文件。

功能：
  AI 自动写入：
  - extract_and_save()：从分析结果提取关键事实并存入 competitor_facts 表
  - get_prior_context()：查询历史事实（含手工备注），格式化为 LLM 可注入的上下文文本
  - has_prior_data()：快速判断某竞品是否有历史数据（用于 UI 提示）
  - list_tracked_competitors()：返回所有有历史数据的竞品名称列表

  PM 手工编辑（#29）：
  - add_manual_note()：添加手工备注（标题 + 内容）
  - get_manual_notes()：获取某竞品所有手工备注
  - update_manual_note()：更新备注内容
  - delete_manual_note()：删除单条备注

增量分析工作流：
  1. 用户输入竞品名 → app.py 调用 has_prior_data() → 如有数据显示提示
  2. 分析启动 → prior_context = get_prior_context() → 传入 Orchestrator.run()
  3. ResearcherAgent 将 prior_context 注入 LLM prompt → 关注变化而非重复历史
  4. 分析完成 → app.py 调用 extract_and_save() → 覆盖保存最新事实
"""
import sqlite3
import config
from core.logger import get_logger

_logger = get_logger(__name__)


class KnowledgeStore:
    # 事实类型标签映射（用于人类可读的上下文输出）
    _LABEL_MAP = {
        "company_overview": "公司概况",
        "business_analysis": "业务分析",
        "feature_matrix": "功能矩阵",
    }

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS competitor_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor TEXT NOT NULL,
                    fact_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            # #29：PM 手工备注表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS manual_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    competitor TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.commit()

    # ── 写入 ─────────────────────────────────────────────────────────

    def save_facts(self, competitor: str, facts: dict):
        """
        覆盖保存竞品事实（先删除旧记录，再批量插入新记录）。
        facts: {fact_type: content_str, ...}
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM competitor_facts WHERE competitor = ?",
                (competitor,),
            )
            for fact_type, content in facts.items():
                if content and content.strip():
                    conn.execute(
                        "INSERT INTO competitor_facts (competitor, fact_type, content) "
                        "VALUES (?, ?, ?)",
                        (competitor, fact_type, str(content)),
                    )
            conn.commit()

    def extract_and_save(self, competitor: str, data: dict):
        """
        从 Orchestrator.run() 返回的 data 中提取关键事实并持久化。
        每次分析完成后调用，自动覆盖旧数据。
        """
        research = data.get("research") or {}
        analysis = data.get("analysis") or {}
        product  = data.get("product")  or {}

        # 字段缺失时记录警告，方便排查 Agent 输出格式变化
        _EXTRACT_MAP = [
            ("company_overview",  research, "summary",        600),
            ("business_analysis", analysis, "analysis",       400),
            ("feature_matrix",    product,  "feature_matrix", 500),
        ]
        facts: dict[str, str] = {}
        for fact_type, source, field, max_len in _EXTRACT_MAP:
            value = source.get(field) or ""
            if not value:
                _logger.warning(
                    "字段缺失 [%s].%s（竞品：%s），知识库跳过写入",
                    fact_type, field, competitor,
                )
            facts[fact_type] = value[:max_len]

        self.save_facts(competitor, facts)

    # ── 读取 ─────────────────────────────────────────────────────────

    def get_prior_context(self, competitor: str) -> str:
        """
        查询历史存储的竞品事实，格式化为 LLM 可读文本。
        若无历史数据返回空字符串。

        返回示例：
            **以下是上次（2026-02-15）对该竞品的分析结论，请作为参考基础，重点关注变化：**

            ### 公司概况
            <摘要文本>

            ### 业务分析
            <摘要文本>
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT fact_type, content, updated_at "
                "FROM competitor_facts "
                "WHERE competitor = ? ORDER BY id ASC",
                (competitor,),
            ).fetchall()

        if not rows:
            return ""

        date_str = rows[0][2][:10] if rows else ""
        parts = [
            f"**以下是上次（{date_str}）对该竞品的分析结论，"
            "请作为参考基础，重点关注与上次相比的变化和更新：**"
        ]
        for fact_type, content, _ in rows:
            label = self._LABEL_MAP.get(fact_type, fact_type)
            parts.append(f"\n### {label}\n{content[:400]}")

        # 追加 PM 手工备注（#29）
        notes = self.get_manual_notes(competitor)
        if notes:
            parts.append("\n### PM 手工补充备注（内部情报，请重点参考）")
            for note in notes:
                parts.append(f"**{note['title']}**（{note['updated_at'][:10]}）：{note['content'][:300]}")

        return "\n".join(parts)

    # ── 查询辅助 ──────────────────────────────────────────────────────

    def has_prior_data(self, competitor: str) -> bool:
        """快速判断某竞品是否有历史事实数据（用于 UI 显示提示）"""
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM competitor_facts WHERE competitor = ?",
                (competitor,),
            ).fetchone()[0]
        return count > 0

    def list_tracked_competitors(self) -> list[str]:
        """返回所有有历史数据的竞品名称（按名称排序）"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT competitor FROM competitor_facts ORDER BY competitor"
            ).fetchall()
        return [r[0] for r in rows]

    def get_last_updated(self, competitor: str) -> str:
        """返回某竞品最近一次更新时间（用于 UI 展示），无数据返回空字符串"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT updated_at FROM competitor_facts "
                "WHERE competitor = ? ORDER BY id DESC LIMIT 1",
                (competitor,),
            ).fetchone()
        return row[0][:16] if row else ""

    # ── 手工备注 CRUD（#29）──────────────────────────────────────────

    def add_manual_note(self, competitor: str, title: str, content: str) -> int:
        """添加一条 PM 手工备注，返回新记录的 id"""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO manual_notes (competitor, title, content) VALUES (?, ?, ?)",
                (competitor, title.strip(), content.strip()),
            )
            conn.commit()
            return cur.lastrowid

    def get_manual_notes(self, competitor: str) -> list[dict]:
        """返回某竞品的所有手工备注列表，按创建时间升序"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, competitor, title, content, created_at, updated_at "
                "FROM manual_notes WHERE competitor = ? ORDER BY id ASC",
                (competitor,),
            ).fetchall()
        return [
            {
                "id": r[0], "competitor": r[1], "title": r[2],
                "content": r[3], "created_at": r[4], "updated_at": r[5],
            }
            for r in rows
        ]

    def update_manual_note(self, note_id: int, title: str, content: str):
        """更新指定 id 的手工备注内容"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE manual_notes SET title = ?, content = ?, "
                "updated_at = datetime('now', 'localtime') WHERE id = ?",
                (title.strip(), content.strip(), note_id),
            )
            conn.commit()

    def delete_manual_note(self, note_id: int):
        """删除指定 id 的手工备注"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM manual_notes WHERE id = ?", (note_id,))
            conn.commit()

    def list_competitors_with_notes(self) -> list[str]:
        """返回有手工备注的竞品列表（供 UI 下拉）"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT competitor FROM manual_notes ORDER BY competitor"
            ).fetchall()
        return [r[0] for r in rows]
