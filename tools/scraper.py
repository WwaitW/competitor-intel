"""
scraper.py — Crawl4AI 网页爬取封装
"""
import asyncio
from typing import Optional

from core.logger import get_logger

_logger = get_logger(__name__)

try:
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False


class ScraperTool:
    def __init__(self):
        self.available = CRAWL4AI_AVAILABLE
        if not self.available:
            _logger.info("[Scraper] crawl4ai 未安装，将跳过网页爬取")

    async def scrape(self, url: str, max_length: int = 3000) -> str:
        """
        爬取指定 URL，返回 LLM 就绪的 Markdown 文本
        """
        if not self.available:
            return f"[爬取跳过] crawl4ai 未安装，无法爬取: {url}"

        try:
            config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url, config=config)
                if result.success:
                    content = result.markdown or result.cleaned_html or ""
                    return content[:max_length]
                else:
                    return f"[爬取失败] {url}: {result.error_message}"
        except Exception as e:
            return f"[爬取异常] {url}: {str(e)}"

    async def scrape_multiple(self, urls: list[str], max_length: int = 2000) -> dict[str, str]:
        """并发爬取多个 URL"""
        tasks = [self.scrape(url, max_length) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            url: (str(r) if isinstance(r, Exception) else r)
            for url, r in zip(urls, results)
        }
