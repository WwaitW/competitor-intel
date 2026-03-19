"""
evaluator.py — 报告质量评估 Agent（反思循环核心）

对四个 Agent 的输出做结构化质量评分：
- score >= 7：通过质检，直接输出报告
- score < 7：返回 gaps 和补充搜索建议，由 orchestrator 触发 retry
"""
import json
import os
import re

from openai import AsyncOpenAI

import config
from core.llm_retry import llm_call_with_retry


class EvaluatorAgent:
    PASS_THRESHOLD = 7  # >= 此分值视为质量合格

    def __init__(self, model: str = None):
        self.model = model or config.DEFAULT_MODEL
        self.llm = AsyncOpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
        )
        self._load_prompt()

    def _load_prompt(self):
        prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/evaluator.txt")
        with open(prompt_path, encoding="utf-8") as f:
            self.system_prompt = f.read()

    async def run(
        self,
        research_data: dict,
        analysis_data: dict,
        product_data: dict,
        strategy_data: dict,
        progress_callback=None,
    ) -> dict:
        """
        输入：四个 Agent 的原始输出
        输出：{score, passed, verdict, gaps, supplement_queries, usage}
        """
        if progress_callback:
            await progress_callback("🔎 评估员正在审查报告质量...")

        competitor = research_data.get("competitor", "")
        context = f"""竞品：{competitor}

=== 调研摘要 ===
{research_data.get("summary", "")[:1500]}

=== 业务分析 ===
{analysis_data.get("analysis", "")[:1000]}

=== 产品功能矩阵 ===
{product_data.get("feature_matrix", "")[:800]}

=== SWOT 与战略建议 ===
{strategy_data.get("strategy", "")[:1000]}"""

        response = await llm_call_with_retry(
            self.llm,
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"请评估以下竞品分析报告的质量：\n\n{context}"},
            ],
            max_tokens=500,
        )

        raw = response.choices[0].message.content
        result = self._parse_result(raw)
        result["usage"] = response.usage.total_tokens if response.usage else 0
        return result

    def _parse_result(self, raw: str) -> dict:
        """
        解析 LLM 返回的 JSON。
        容错策略：解析失败时默认评分 7 分（通过），避免阻断主流程。
        """
        try:
            # 优先提取 ```json ... ``` 代码块
            match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
            json_str = match.group(1) if match else raw.strip()
            data = json.loads(json_str)

            score = max(1, min(10, int(data.get("score", 7))))
            return {
                "score": score,
                "passed": score >= self.PASS_THRESHOLD,
                "verdict": str(data.get("verdict", ""))[:50],
                "gaps": [str(g) for g in data.get("gaps", [])][:3],
                "supplement_queries": [str(q) for q in data.get("supplement_queries", [])][:3],
            }
        except Exception:
            return {
                "score": 7,
                "passed": True,
                "verdict": "评估解析异常，默认通过",
                "gaps": [],
                "supplement_queries": [],
            }
