"""
webhook_notifier.py — Webhook 通知模块（#30）

支持三个平台：钉钉 / 飞书 / Slack
  - 检测到对应 URL 已配置时自动推送，未配置则静默跳过
  - 全部使用标准库 urllib（无额外依赖）
  - 异步入口：send_all()  — asyncio 线程池调用同步 HTTP
  - 同步入口：send_all_sync()  — 兼容非异步场景

平台 Webhook 创建指南：
  钉钉：钉钉群 → 智能群助手 → 添加机器人 → 自定义（关键词：竞品雷达）
  飞书：飞书群 → 设置 → 机器人 → 添加机器人 → 自定义机器人
  Slack：Slack 工作区 → 应用 → Incoming WebHooks → Add to Slack
"""
from __future__ import annotations

import asyncio
import json
import urllib.request
from datetime import datetime

from core.logger import get_logger

_logger = get_logger(__name__)


def _post_json(url: str, payload: dict, timeout: int = 8) -> bool:
    """向 url POST JSON，成功返回 True，失败打印日志返回 False。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            # 各平台成功响应：钉钉 {"errcode":0}，飞书 {"code":0}，Slack "ok"
            ok = ('"errcode":0' in body or '"code":0' in body
                  or body.strip() == "ok" or '"ok":true' in body)
            if not ok:
                _logger.warning("推送响应异常: %s", body[:120])
            return ok
    except Exception as e:
        _logger.error("推送失败 (%s...): %s", url[:40], e)
        return False


class WebhookNotifier:
    """封装钉钉 / 飞书 / Slack 推送逻辑"""

    def __init__(
        self,
        dingtalk_url: str = "",
        feishu_url: str = "",
        slack_url: str = "",
    ):
        self.dingtalk_url = dingtalk_url.strip()
        self.feishu_url = feishu_url.strip()
        self.slack_url = slack_url.strip()

    # ── 各平台推送（同步）────────────────────────────────────────────

    def _send_dingtalk(self, title: str, body: str) -> bool:
        """
        钉钉自定义机器人 — markdown 消息。
        注意：消息 text 必须包含机器人配置的「安全关键词」（默认：竞品雷达）。
        此处在消息末尾强制追加标签，确保关键词始终存在，防止 45008 错误。
        """
        if not self.dingtalk_url:
            return False
        text = f"## {title}\n\n{body}"
        # 安全关键词保障：若 title/body 中均不含「竞品雷达」，在末尾补充标签
        if "竞品雷达" not in text:
            text += "\n\n> 竞品雷达"
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": text,
            },
        }
        ok = _post_json(self.dingtalk_url, payload)
        if ok:
            _logger.info("[钉钉] 已推送: %s", title)
        return ok

    def _send_feishu(self, title: str, body: str) -> bool:
        """飞书自定义机器人 — 富文本消息（post 类型）"""
        if not self.feishu_url:
            return False
        # 将 body 按行分割，构建飞书富文本段落
        content_lines = []
        for line in body.splitlines():
            if line.strip():
                # 去除 Markdown 符号，保留纯文本
                clean = line.lstrip("#- *").strip()
                if clean:
                    content_lines.append([{"tag": "text", "text": clean}])

        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": content_lines or [[{"tag": "text", "text": body[:400]}]],
                    }
                }
            },
        }
        ok = _post_json(self.feishu_url, payload)
        if ok:
            _logger.info("[飞书] 已推送: %s", title)
        return ok

    def _send_slack(self, title: str, body: str) -> bool:
        """Slack Incoming Webhook — Block Kit 格式"""
        if not self.slack_url:
            return False
        payload = {
            "text": title,   # 通知摘要（桌面推送显示）
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": title, "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": body[:2900]},
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Intelix · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        }
                    ],
                },
            ],
        }
        ok = _post_json(self.slack_url, payload)
        if ok:
            _logger.info("[Slack] 已推送: %s", title)
        return ok

    # ── 对外接口 ─────────────────────────────────────────────────────

    def send_all_sync(self, competitor: str, summary: str):
        """同步推送到所有已配置的平台（change_detector._save 直接调用）"""
        title = f"[竞品雷达] {competitor} 检测到新变更"
        self._send_dingtalk(title, summary)
        self._send_feishu(title, summary)
        self._send_slack(title, summary)

    async def send_all(self, competitor: str, summary: str):
        """异步推送（run_in_executor 包装同步调用，不阻塞事件循环）"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.send_all_sync, competitor, summary)
