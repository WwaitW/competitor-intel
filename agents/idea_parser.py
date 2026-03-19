"""
idea_parser.py — 想法解析 Agent（IdeaDiscovery 功能核心）

输入：用户自然语言描述的产品/业务想法
输出：
  {
    "idea_summary": str,       # 一句话核心
    "target_users": str,       # 目标用户
    "core_value": str,         # 核心价值主张
    "key_problem": str,        # 解决的问题
    "competitors": [str, ...], # 3~5 个相关竞品名
    "market_keywords": [str],  # 市场关键词
    "usage": int               # 消耗 token 数
  }
"""
import json
import os
import re

from openai import AsyncOpenAI

import config
from core.llm_retry import llm_call_with_retry


def _strip_code_fence(text: str) -> str:
    """去除 LLM 输出的 markdown 代码块包裹"""
    text = text.strip()
    # 去除 ```json ... ``` 或 ``` ... ```
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


class IdeaParserAgent:
    """解析用户想法并发现相关竞品"""

    def __init__(self, model: str = None):
        self.model = model or config.DEFAULT_MODEL
        self.llm = AsyncOpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
        )
        self._load_prompt()

    def _load_prompt(self):
        prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/idea_parser.txt")
        with open(prompt_path, encoding="utf-8") as f:
            self.system_prompt = f.read()

    async def run(self, idea: str, progress_callback=None) -> dict:
        """
        解析想法 + 发现竞品。

        参数：
            idea             — 用户描述的产品/业务想法
            progress_callback — 异步回调，接收进度字符串

        返回 dict，字段见模块头部注释。
        """
        if progress_callback:
            await progress_callback("💡 正在解析你的想法...")

        user_msg = f"请解析以下产品/业务想法，并推荐相关竞品：\n\n{idea.strip()}"

        response = await llm_call_with_retry(
            self.llm,
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=800,
        )

        raw = response.choices[0].message.content
        usage = response.usage.total_tokens if response.usage else 0

        result = self._parse_result(raw)
        result["usage"] = usage
        return result

    def _parse_result(self, raw: str) -> dict:
        """
        解析 LLM 返回的 JSON。
        容错策略：
          1. 先尝试直接 JSON 解析
          2. 失败则用正则从文本提取竞品列表，其余字段置空
        """
        cleaned = _strip_code_fence(raw)

        try:
            data = json.loads(cleaned)
            competitors = [str(c).strip() for c in data.get("competitors", []) if str(c).strip()][:5]
            keywords = [str(k).strip() for k in data.get("market_keywords", []) if str(k).strip()][:8]
            return {
                "idea_summary": str(data.get("idea_summary", ""))[:200],
                "target_users": str(data.get("target_users", ""))[:200],
                "core_value": str(data.get("core_value", ""))[:200],
                "key_problem": str(data.get("key_problem", ""))[:200],
                "competitors": competitors,
                "market_keywords": keywords,
            }
        except (json.JSONDecodeError, Exception):
            # Fallback：正则提取列表项作为竞品
            competitors = re.findall(
                r'(?:competitors|竞品)["\s:]*\[([^\]]+)\]',
                raw,
                re.IGNORECASE | re.DOTALL,
            )
            if competitors:
                items = re.findall(r'"([^"]+)"', competitors[0])
                items = [i.strip() for i in items if i.strip()][:5]
            else:
                # 最后兜底：从文本中找引号包裹的词
                items = re.findall(r'"([A-Za-z\u4e00-\u9fff][^"]{1,30})"', raw)[:5]

            return {
                "idea_summary": "",
                "target_users": "",
                "core_value": "",
                "key_problem": "",
                "competitors": items,
                "market_keywords": [],
            }
