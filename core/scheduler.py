"""
scheduler.py — 竞品监控调度器（P4.1）

职责：
  - 维护"监控列表"：哪些竞品需要定期自动重跑分析
  - 定时触发 Orchestrator + ChangeDetector，将变更摘要写入 change_logs
  - 与 Streamlit 共享同一进程（BackgroundScheduler），@st.cache_resource 单例

数据库表（与 history.db 共享）：
  monitor_jobs   — 监控任务配置（competitor / interval_hours / next_run_at / enabled）

调用方：app.py
  scheduler = get_scheduler()
  scheduler.add_job("Notion", interval_hours=168)   # 每周
  scheduler.remove_job("Notion")
  scheduler.list_jobs()                             # → list[dict]
"""
import sqlite3
import asyncio
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import config
from core.logger import get_logger

_logger = get_logger(__name__)


# ── 数据库 ─────────────────────────────────────────────────────────────

def _init_monitor_table(db_path: str):
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monitor_jobs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                competitor      TEXT NOT NULL UNIQUE,
                our_product     TEXT DEFAULT '',
                interval_hours  INTEGER DEFAULT 168,
                next_run_at     TEXT,
                last_run_at     TEXT,
                enabled         INTEGER DEFAULT 1,
                created_at      TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.commit()


# ── 调度器主类 ──────────────────────────────────────────────────────────

class CompetitorScheduler:
    """
    竞品定时监控调度器（单例，随 Streamlit 进程存活）

    内部使用 APScheduler BackgroundScheduler 在独立线程中运行定时任务。
    每个 monitor_job 对应一个 APScheduler job，job_id = competitor 名称。
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        _init_monitor_table(self.db_path)
        self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._scheduler.start()
        self._lock = threading.Lock()
        # 恢复已有监控任务（服务重启后重新注册）
        self._restore_jobs()

    # ── 对外接口 ─────────────────────────────────────────────────────

    def add_job(
        self,
        competitor: str,
        our_product: str = "",
        interval_hours: int = 168,
    ):
        """
        添加或更新监控任务。
        interval_hours=168 → 每周；interval_hours=24 → 每天
        """
        next_run_at = (
            datetime.now() + timedelta(hours=interval_hours)
        ).strftime("%Y-%m-%d %H:%M")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO monitor_jobs (competitor, our_product, interval_hours, next_run_at, enabled)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(competitor) DO UPDATE SET
                    our_product    = excluded.our_product,
                    interval_hours = excluded.interval_hours,
                    next_run_at    = excluded.next_run_at,
                    enabled        = 1
            """, (competitor, our_product, interval_hours, next_run_at))
            conn.commit()

        self._register_apscheduler_job(competitor, our_product, interval_hours)

    def remove_job(self, competitor: str):
        """停止并删除监控任务"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE monitor_jobs SET enabled = 0 WHERE competitor = ?",
                (competitor,),
            )
            conn.commit()

        job_id = self._job_id(competitor)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    def list_jobs(self) -> list[dict]:
        """返回所有启用中的监控任务"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM monitor_jobs WHERE enabled = 1 ORDER BY competitor"
            ).fetchall()
        return [dict(r) for r in rows]

    def is_monitoring(self, competitor: str) -> bool:
        """检查某竞品是否正在监控中"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT enabled FROM monitor_jobs WHERE competitor = ?",
                (competitor,),
            ).fetchone()
        return bool(row and row[0] == 1)

    def run_now(self, competitor: str):
        """立即触发一次监控任务（不等待下次定时）"""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT our_product, interval_hours FROM monitor_jobs WHERE competitor = ? AND enabled = 1",
                (competitor,),
            ).fetchone()
        if row:
            our_product, interval_hours = row
            self._run_analysis(competitor, our_product)

    def shutdown(self):
        """关闭调度器（进程退出时调用）"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    # ── 内部逻辑 ─────────────────────────────────────────────────────

    @staticmethod
    def _job_id(competitor: str) -> str:
        return f"monitor_{competitor}"

    def _register_apscheduler_job(
        self,
        competitor: str,
        our_product: str,
        interval_hours: int,
    ):
        """向 APScheduler 注册（或替换）定时 Job"""
        job_id = self._job_id(competitor)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

        self._scheduler.add_job(
            func=self._run_analysis,
            trigger=IntervalTrigger(hours=interval_hours),
            id=job_id,
            args=[competitor, our_product],
            replace_existing=True,
            misfire_grace_time=3600,  # 错过触发时最多允许 1 小时内补跑
        )

    def _run_analysis(self, competitor: str, our_product: str):
        """
        实际执行分析 + 变更检测（在 APScheduler 后台线程中运行）。
        使用独立的 event loop 运行异步 Orchestrator。
        """
        with self._lock:
            try:
                _logger.info("开始监控分析：%s", competitor)
                loop = asyncio.new_event_loop()
                # 注意：不调用 asyncio.set_event_loop()，避免与 Streamlit 主线程 event loop 冲突
                try:
                    loop.run_until_complete(
                        self._async_run_analysis(competitor, our_product)
                    )
                finally:
                    loop.close()

                # 更新最后运行时间
                next_run_at = (
                    datetime.now() + timedelta(hours=self._get_interval(competitor))
                ).strftime("%Y-%m-%d %H:%M")
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        "UPDATE monitor_jobs SET last_run_at = datetime('now','localtime'), "
                        "next_run_at = ? WHERE competitor = ?",
                        (next_run_at, competitor),
                    )
                    conn.commit()

                _logger.info("监控分析完成：%s", competitor)
            except Exception as e:
                _logger.error("监控分析失败 %s: %s", competitor, e, exc_info=True)

    async def _async_run_analysis(self, competitor: str, our_product: str):
        """异步执行：Orchestrator 分析 → KnowledgeStore 存新数据 → ChangeDetector 检测变更"""
        from core.orchestrator import Orchestrator
        from core.knowledge_store import KnowledgeStore
        from core.change_detector import ChangeDetector

        ks = KnowledgeStore(self.db_path)
        cd = ChangeDetector(self.db_path)

        # 获取旧数据（在分析前快照，用于对比）
        old_context = ks.get_prior_context(competitor)

        # 运行分析（无进度回调）
        orch = Orchestrator()
        data = await orch.run(
            competitor=competitor,
            our_product=our_product,
            prior_context=old_context,
        )

        # 存新数据
        ks.extract_and_save(competitor, data)

        # 检测变更（旧 vs 新）
        if old_context:
            await cd.detect_and_save(competitor, old_context, data)

    def _get_interval(self, competitor: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT interval_hours FROM monitor_jobs WHERE competitor = ?",
                (competitor,),
            ).fetchone()
        return row[0] if row else 168

    def _restore_jobs(self):
        """服务重启后恢复已有的 APScheduler 任务"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT competitor, our_product, interval_hours FROM monitor_jobs WHERE enabled = 1"
            ).fetchall()
        for row in rows:
            self._register_apscheduler_job(
                row["competitor"], row["our_product"], row["interval_hours"]
            )
        if rows:
            _logger.info("恢复 %d 个监控任务", len(rows))
