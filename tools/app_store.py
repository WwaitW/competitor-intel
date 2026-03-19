"""
app_store.py — 应用商店评论抓取（通过搜索获取评价摘要）
"""
import asyncio
from tools.web_search import WebSearchTool


class AppStoreTool:
    def __init__(self):
        self.searcher = WebSearchTool()

    async def get_reviews_summary(self, product_name: str) -> str:
        """通过搜索引擎获取用户评价摘要"""
        queries = [
            f"{product_name} reviews G2 user feedback",
            f"{product_name} ProductHunt reviews pros cons",
            f"{product_name} 用户评价 优缺点",
        ]
        all_results = []
        tasks = [self.searcher.async_search(q, max_results=3) for q in queries]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for results in results_list:
            if isinstance(results, list):
                all_results.extend(results)

        return self.searcher.format_results(all_results[:8])
