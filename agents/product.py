"""
product.py — 产品对比代理
负责：生成功能对比矩阵（Markdown 表格）
"""
import os
from openai import AsyncOpenAI
import config
from core.llm_retry import llm_call_with_retry


class ProductAgent:
    def __init__(self, model: str = None):
        self.model = model or config.DEFAULT_MODEL
        self.llm = AsyncOpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
        )
        self._load_prompt()

    def _load_prompt(self):
        prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/product.txt")
        with open(prompt_path, encoding="utf-8") as f:
            self.system_prompt = f.read()

    async def run(self, research_data: dict, analysis_data: dict, our_product: str = "", progress_callback=None) -> dict:
        """
        输入: research_data + analysis_data（+ 可选自己产品）
        输出: {feature_matrix, positioning, usage}
        """
        if progress_callback:
            await progress_callback("📋 产品经理正在生成功能对比矩阵...")

        competitor = research_data["competitor"]
        context = f"""
竞品名称：{competitor}
{"我方产品：" + our_product if our_product else "（单竞品分析模式）"}

调研摘要：
{research_data['summary']}

业务分析：
{analysis_data['analysis']}

官网产品信息：
{research_data['website_info'][:1500]}
"""
        response = await llm_call_with_retry(
            self.llm,
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"请生成「{competitor}」的功能对比矩阵：\n\n{context}"},
            ],
            max_tokens=1500,
        )
        matrix = response.choices[0].message.content

        return {
            "competitor": competitor,
            "feature_matrix": matrix,
            "usage": response.usage.total_tokens if response.usage else 0,
        }
