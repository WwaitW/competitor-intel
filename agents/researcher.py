"""
researcher.py — 市场调研代理
负责：搜索官网、新闻、用户评价、招聘信号（并发执行）
"""
import asyncio
import os
import re
from openai import AsyncOpenAI
from tools.web_search import WebSearchTool
from tools.scraper import ScraperTool
import config
from core.llm_retry import llm_call_with_retry


def _strip_code_fence(text: str) -> str:
    """去除 LLM 可能错误添加的 ```markdown ... ``` 包裹"""
    text = text.strip()
    m = re.match(r'^```(?:markdown)?\s*\n([\s\S]*?)```\s*$', text)
    if m:
        return m.group(1).strip()
    return text


class ResearcherAgent:
    def __init__(self, model: str = None):
        self.model = model or config.DEFAULT_MODEL
        self.llm = AsyncOpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
        )
        self.searcher = WebSearchTool()
        self.scraper = ScraperTool()
        self._load_prompt()

    def _load_prompt(self):
        prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/researcher.txt")
        with open(prompt_path, encoding="utf-8") as f:
            self.system_prompt = f.read()

    async def _gather_website_info(self, competitor: str) -> tuple[str, list[dict]]:
        """搜索并爬取官网信息，返回 (格式化文本, 原始结果列表)"""
        results = await self.searcher.async_search(
            f"{competitor} official website features pricing",
            max_results=5,
            search_depth="advanced",
            require_keyword=competitor,
            days=180,   # 官网/产品信息：近6个月
        )
        text = self.searcher.format_results(results)

        # 尝试爬取官网首页
        if results:
            top_url = results[0].get("url", "")
            if top_url:
                scraped = await self.scraper.scrape(top_url, max_length=2000)
                text += f"\n\n**官网内容摘要**:\n{scraped}"
        return text, results

    async def _gather_news(self, competitor: str) -> tuple[str, list[dict]]:
        """搜索近90天新闻（覆盖产品演化轨迹），返回 (格式化文本, 原始结果列表)"""
        results = await self.searcher.async_news_search(
            f"{competitor} news update launch 2025 2026",
            max_results=5,
            require_keyword=competitor,
            days=90,    # 新闻/动态：近3个月，支撑产品演化轨迹分析
        )
        return self.searcher.format_results(results), results

    async def _gather_reviews(self, competitor: str) -> tuple[str, list[dict]]:
        """并发搜索两路评价数据（平台评分 + 用户痛点），合并去重后返回"""
        # 路一：G2/Capterra 等专业评价平台（include_domains 精准命中）
        # 路二：用户抱怨/痛点信号（"problems complaints users dislike"）
        platform_results, pain_results = await asyncio.gather(
            self.searcher.async_search(
                f"{competitor} reviews rating pros cons user feedback",
                max_results=4,
                require_keyword=competitor,
                days=365,
                include_domains=config.REVIEW_PLATFORM_DOMAINS,
            ),
            self.searcher.async_search(
                f"{competitor} problems complaints users dislike issues 2025 2026",
                max_results=3,
                require_keyword=competitor,
                days=180,   # 痛点信号要近期，反映当前产品状态
            ),
        )
        # 合并去重（URL 去重，平台结果优先在前）
        seen: set[str] = set()
        merged: list[dict] = []
        for r in platform_results + pain_results:
            url = r.get("url", "")
            if url not in seen:
                seen.add(url)
                merged.append(r)
        return self.searcher.format_results(merged), merged

    async def _gather_hiring(self, competitor: str) -> tuple[str, list[dict]]:
        """搜索招聘信号，返回 (格式化文本, 原始结果列表)"""
        results = await self.searcher.async_search(
            f"{competitor} hiring jobs LinkedIn engineer 2025 2026",
            max_results=3,
            require_keyword=competitor,
            days=90,    # 招聘信号：近3个月（反映当前研发方向）
        )
        return self.searcher.format_results(results), results

    @staticmethod
    def _build_numbered_sources(
        website_results: list[dict],
        news_results: list[dict],
        reviews_results: list[dict],
        hiring_results: list[dict],
    ) -> tuple[list[dict], str]:
        """
        将四类搜索结果合并为有编号的来源列表，
        返回 (sources, numbered_header)。
        sources: [{"id": 1, "title": ..., "url": ...}, ...]
        numbered_header: 注入 raw_data 顶部的文本，供 LLM 引用编号
        """
        seen_urls: set[str] = set()
        sources: list[dict] = []

        for group in (website_results, news_results, reviews_results, hiring_results):
            for r in (group or []):
                url = r.get("url", "").strip()
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    sources.append({
                        "id": len(sources) + 1,
                        "title": r.get("title", url)[:80],
                        "url": url,
                    })

        header_lines = ["**可引用来源编号（在关键数据后加 [N]）**："]
        for s in sources:
            header_lines.append(f"[{s['id']}] {s['title']} — {s['url']}")
        header = "\n".join(header_lines) + "\n\n"

        return sources, header

    async def run(
        self,
        competitor: str,
        progress_callback=None,
        prior_context: str = "",
    ) -> dict:
        """
        并发执行所有数据采集任务
        返回: {website, news, reviews, hiring, summary}

        prior_context: 历史分析摘要（由 KnowledgeStore.get_prior_context() 提供）；
                       非空时注入 LLM prompt，引导模型关注变化而非重复历史。
        """
        if progress_callback:
            label = "🔍 研究员正在并发采集数据（含历史对比）..." if prior_context else "🔍 研究员正在并发采集数据..."
            await progress_callback(label)

        (website_info, website_results), (news_info, news_results), \
        (reviews_info, reviews_results), (hiring_info, hiring_results) = \
            await asyncio.gather(
                self._gather_website_info(competitor),
                self._gather_news(competitor),
                self._gather_reviews(competitor),
                self._gather_hiring(competitor),
            )

        # 构建编号来源列表
        sources, numbered_header = self._build_numbered_sources(
            website_results, news_results, reviews_results, hiring_results
        )

        if progress_callback:
            await progress_callback("🤖 研究员正在生成调研摘要...")

        raw_data = f"""{numbered_header}
## 官网与产品信息
{website_info}

## 近期新闻动态
{news_info}

## 用户评价
{reviews_info}

## 招聘信号
{hiring_info}
"""
        # 增量分析：将历史数据作为背景上下文注入
        prior_section = (
            f"\n\n{prior_context}\n\n"
            if prior_context
            else ""
        )

        response = await llm_call_with_retry(
            self.llm,
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"请对竞品「{competitor}」进行调研分析。"
                        f"{prior_section}"
                        f"以下是最新搜索到的原始数据：\n\n{raw_data}"
                    ),
                },
            ],
            max_tokens=2000,
        )
        summary = _strip_code_fence(response.choices[0].message.content)

        return {
            "competitor": competitor,
            "website_info": website_info,
            "news_info": news_info,
            "reviews_info": reviews_info,
            "hiring_info": hiring_info,
            "summary": summary,
            "sources": sources,   # [{id, title, url}, ...]  新增
            "usage": response.usage.total_tokens if response.usage else 0,
        }
