"""
strategist.py — 战略顾问代理
负责：综合所有信息生成 SWOT + 战略建议
"""
import os
from openai import AsyncOpenAI
import config
from core.llm_retry import llm_call_with_retry


class StrategistAgent:
    def __init__(self, model: str = None):
        self.model = model or config.DEFAULT_MODEL
        self.llm = AsyncOpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
        )
        self._load_prompt()

    def _load_prompt(self):
        prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/strategist.txt")
        with open(prompt_path, encoding="utf-8") as f:
            self.system_prompt = f.read()

    async def run(
        self,
        research_data: dict,
        analysis_data: dict,
        product_data: dict,
        our_product: str = "",
        progress_callback=None,
    ) -> dict:
        """
        综合所有 agent 的输出，生成 SWOT + 战略建议
        """
        if progress_callback:
            await progress_callback("🧠 战略顾问正在生成 SWOT 与战略建议...")

        competitor = research_data["competitor"]

        # 构建编号来源头（与 researcher 使用相同的编号体系，#31）
        sources = research_data.get("sources", [])
        if sources:
            source_lines = ["**可引用来源编号（在关键数据后加 [N]）**："]
            for s in sources:
                source_lines.append(f"[{s['id']}] {s['title']} — {s['url']}")
            sources_header = "\n".join(source_lines) + "\n\n"
        else:
            sources_header = ""

        context = f"""{sources_header}竞品名称：{competitor}
{"我方产品：" + our_product if our_product else "（通用战略分析）"}

=== 调研摘要 ===
{research_data['summary']}

=== 业务分析 ===
{analysis_data['analysis']}

=== 功能矩阵 ===
{product_data['feature_matrix']}

=== 用户评价（含平台评分与用户痛点信号）===
{research_data['reviews_info'][:2500]}
"""
        response = await llm_call_with_retry(
            self.llm,
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"请对「{competitor}」进行 SWOT 分析并给出战略建议：\n\n{context}"},
            ],
            max_tokens=2000,
        )
        strategy = response.choices[0].message.content

        return {
            "competitor": competitor,
            "strategy": strategy,
            "usage": response.usage.total_tokens if response.usage else 0,
        }
