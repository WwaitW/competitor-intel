"""
analyst.py — 财务/新闻分析代理
负责：解析融资、收入、规模、近期重大事件
"""
import os
from openai import AsyncOpenAI
import config
from core.llm_retry import llm_call_with_retry


class AnalystAgent:
    def __init__(self, model: str = None):
        self.model = model or config.DEFAULT_MODEL
        self.llm = AsyncOpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
        )
        self._load_prompt()

    def _load_prompt(self):
        prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/analyst.txt")
        with open(prompt_path, encoding="utf-8") as f:
            self.system_prompt = f.read()

    async def run(self, research_data: dict, progress_callback=None) -> dict:
        """
        输入: researcher_agent 的输出
        输出: {analysis, funding, market_size, recent_events, usage}
        """
        if progress_callback:
            await progress_callback("📊 分析师正在解析市场数据...")

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

调研摘要：
{research_data['summary']}

新闻动态原始数据：
{research_data['news_info']}

招聘信号原始数据：
{research_data['hiring_info']}
"""
        response = await llm_call_with_retry(
            self.llm,
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"请对竞品「{competitor}」进行深度业务分析：\n\n{context}"},
            ],
            max_tokens=1500,
        )
        analysis = response.choices[0].message.content

        return {
            "competitor": competitor,
            "analysis": analysis,
            "usage": response.usage.total_tokens if response.usage else 0,
        }
