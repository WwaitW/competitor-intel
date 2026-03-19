"""
change_detector.py — 竞品变更检测器（P4.2）

职责：
  对比同一竞品"上次分析"与"本次分析"的结果，
  用 LLM 生成精简的"变更摘要"，只描述有实质变化的点。

数据库表（与 history.db 共享）：
  change_logs  — 变更记录（competitor / summary / detected_at / is_read）

核心方法：
  detect_and_save(competitor, old_context, new_data)
    → 对比新旧数据 → LLM 生成变更摘要 → 写入 change_logs
  list_unread(limit)  → 返回未读变更列表
  mark_read(change_id)
  list_all(competitor, limit)
"""
import json
import sqlite3
from datetime import datetime

from openai import AsyncOpenAI

import config
from core.webhook_notifier import WebhookNotifier
from core.llm_retry import llm_call_with_retry
from core.logger import get_logger

_logger = get_logger(__name__)


# ── 数据库初始化 ──────────────────────────────────────────────────────

def _init_change_table(db_path: str):
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS change_logs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                competitor   TEXT NOT NULL,
                summary      TEXT NOT NULL,
                detected_at  TEXT DEFAULT (datetime('now', 'localtime')),
                is_read      INTEGER DEFAULT 0
            )
        """)
        conn.commit()


# ── 变更检测器 ────────────────────────────────────────────────────────

class ChangeDetector:
    # LLM 用于生成变更摘要的 System Prompt
    _SYSTEM_PROMPT = """你是一名竞品情报分析师，专门识别竞品的重要变化。

你将收到同一竞品的"上次分析结论"与"本次分析结论"。

任务：对比两份数据，只提取**有实质变化的点**，忽略措辞差异和无关信息。
重点关注：定价调整、新功能发布、融资/裁员、战略转向、市场份额变化、高管变动。

输出格式（Markdown，简洁为主）：
如有变化：
## 检测到变化
- **[变化类型]** 具体描述（对比：上次 → 本次）

如无实质变化：
## 无重大变化
简短说明（一句话）

规则：
- 每条变化不超过 50 字
- 最多输出 5 条
- 无变化时绝不捏造"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        _init_change_table(self.db_path)
        self._llm = None  # 延迟初始化：仅在首次调用时创建，避免 Key 未配置时静默失败

    @property
    def llm(self) -> AsyncOpenAI:
        """懒初始化 LLM 客户端，Key 未配置时抛出明确错误"""
        if self._llm is None:
            api_key = config.OPENROUTER_API_KEY
            if not api_key:
                raise RuntimeError(
                    "OpenRouter API Key 未配置，变更检测无法运行。"
                    "请在侧边栏填写 API Key。"
                )
            self._llm = AsyncOpenAI(
                api_key=api_key,
                base_url=config.OPENROUTER_BASE_URL,
            )
        return self._llm

    # ── 核心方法 ─────────────────────────────────────────────────────

    async def detect_and_save(
        self,
        competitor: str,
        old_context: str,
        new_data: dict,
    ) -> str:
        """
        对比旧数据（old_context 文本）与新数据（new_data dict），
        生成变更摘要并存入 change_logs。
        返回变更摘要文本。
        """
        new_context = self._extract_new_context(competitor, new_data)

        user_msg = f"""竞品：{competitor}

=== 上次分析结论 ===
{old_context[:3000]}

=== 本次分析结论 ===
{new_context[:3000]}"""

        try:
            resp = await llm_call_with_retry(
                self.llm,
                model=config.DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": self._SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=400,
            )
            summary = resp.choices[0].message.content.strip()
        except Exception as e:
            summary = f"## 变更检测失败\n{e}"

        # 只保存有实质变化的记录
        if "无重大变化" not in summary:
            self._save(competitor, summary)

        return summary

    # ── 查询接口 ─────────────────────────────────────────────────────

    def list_unread(self, limit: int = 20) -> list[dict]:
        """返回所有未读变更，按时间倒序"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM change_logs WHERE is_read = 0 "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_all(self, competitor: str = "", limit: int = 30) -> list[dict]:
        """返回变更记录（可按竞品过滤）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if competitor:
                rows = conn.execute(
                    "SELECT * FROM change_logs WHERE competitor = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (competitor, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM change_logs ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def mark_read(self, change_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE change_logs SET is_read = 1 WHERE id = ?",
                (change_id,),
            )
            conn.commit()

    def mark_all_read(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE change_logs SET is_read = 1")
            conn.commit()

    def unread_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM change_logs WHERE is_read = 0"
            ).fetchone()[0]

    # ── 内部工具 ─────────────────────────────────────────────────────

    def _save(self, competitor: str, summary: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO change_logs (competitor, summary) VALUES (?, ?)",
                (competitor, summary),
            )
            conn.commit()
        self._send_email_notification(competitor, summary)
        # Webhook 通知（#30）
        WebhookNotifier(
            dingtalk_url=config.NOTIFY_DINGTALK_WEBHOOK,
            feishu_url=config.NOTIFY_FEISHU_WEBHOOK,
            slack_url=config.NOTIFY_SLACK_WEBHOOK,
        ).send_all_sync(competitor, summary)

    def _send_email_notification(self, competitor: str, summary: str):
        """发送邮件通知（需配置 NOTIFY_* 环境变量）"""
        if not (config.NOTIFY_EMAIL_TO and config.NOTIFY_SMTP_USER and config.NOTIFY_SMTP_PASS):
            return
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        subject = f"[竞品雷达] {competitor} 发现新变更"
        body = (
            f"竞品「{competitor}」检测到以下变化：\n\n"
            f"{summary}\n\n"
            f"---\n此邮件由 Intelix 自动发送。"
        )
        msg = MIMEMultipart()
        msg["From"] = config.NOTIFY_EMAIL_FROM or config.NOTIFY_SMTP_USER
        msg["To"] = config.NOTIFY_EMAIL_TO
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        try:
            with smtplib.SMTP(config.NOTIFY_SMTP_HOST, config.NOTIFY_SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(config.NOTIFY_SMTP_USER, config.NOTIFY_SMTP_PASS)
                server.send_message(msg)
            _logger.info("邮件通知已发送至 %s", config.NOTIFY_EMAIL_TO)
        except Exception as e:
            _logger.error("邮件发送失败: %s", e)

    @staticmethod
    def _extract_new_context(competitor: str, data: dict) -> str:
        """从本次分析数据中提取与 old_context 可对比的文本"""
        research = data.get("research") or {}
        analysis = data.get("analysis") or {}
        product = data.get("product") or {}
        strategy = data.get("strategy") or {}

        parts = [f"竞品：{competitor}"]
        if research.get("summary"):
            parts.append(f"### 公司概况\n{research['summary'][:900]}")
        if analysis.get("analysis"):
            parts.append(f"### 业务分析\n{analysis['analysis'][:700]}")
        if product.get("feature_matrix"):
            parts.append(f"### 功能矩阵\n{product['feature_matrix'][:700]}")
        if strategy.get("strategy"):
            parts.append(f"### SWOT\n{strategy['strategy'][:600]}")
        return "\n\n".join(parts)
