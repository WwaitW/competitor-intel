"""
web_search.py — 搜索工具封装

Fallback 链：Tavily（主）→ DuckDuckGo（兜底，免费无需 Key）
双重过滤：
  ResultFilter  — 质量门控（score 排序 / 去重 / 短内容 / 黑名单 / 单域名限制）
  DiversityFilter — 内容多样性（n-gram Jaccard 贪心去重，剔除相似结果）
"""
import asyncio
from urllib.parse import urlparse

import config
from core.logger import get_logger
from core.search_cache import SearchCache

_logger = get_logger(__name__)


def _extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


class ResultFilter:
    """搜索结果质量过滤器"""

    # 对竞品分析无实质帮助的低质量域名
    _BLOCKLIST: set[str] = {
        "pinterest.com", "slideshare.net", "scribd.com",
        "issuu.com", "amazon.com", "ebay.com",
        "etsy.com", "walmart.com", "yelp.com",
    }

    @classmethod
    def filter(
        cls,
        results: list[dict],
        min_content_len: int = 80,
        max_per_domain: int = 2,
        require_keyword: str = "",
    ) -> list[dict]:
        """
        过滤流程：
        1. 按 score 降序排列（高质量优先）
        2. 去重 URL
        3. 丢弃内容过短（< min_content_len）的结果
        4. 丢弃黑名单域名
        5. 单域名最多保留 max_per_domain 条（防止来源单一）
        6. 关键词相关性检查：title + content 必须包含 require_keyword（大小写不敏感）
        """
        seen_urls: set[str] = set()
        domain_counts: dict[str, int] = {}
        filtered: list[dict] = []
        kw = require_keyword.lower() if require_keyword else ""

        sorted_results = sorted(results, key=lambda x: x.get("score", 0), reverse=True)

        for r in sorted_results:
            url = r.get("url", "")
            content = r.get("content", "")

            if url in seen_urls:
                continue
            if len(content) < min_content_len:
                continue

            domain = _extract_domain(url)
            if domain in cls._BLOCKLIST:
                continue
            if domain_counts.get(domain, 0) >= max_per_domain:
                continue

            # 关键词相关性：title 或 content 中必须出现竞品名
            if kw and kw not in (r.get("title", "") + " " + content).lower():
                continue

            seen_urls.add(url)
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            filtered.append(r)

        return filtered


# ── 多样性过滤（P2.1）────────────────────────────────────────────────

def _ngram_jaccard(a: str, b: str, n: int = 3) -> float:
    """
    计算两段文本的 n-gram Jaccard 相似度（纯 Python，无外部依赖）。
    相似度范围 [0, 1]，值越大越相似。
    任一文本词数 < n（无法提取 n-gram）时返回 0.0（视为不相似，不过滤）。
    """
    def to_ngrams(text: str) -> set:
        words = text.lower().split()
        if len(words) < n:
            return set()
        return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}

    sa, sb = to_ngrams(a), to_ngrams(b)
    if not sa or not sb:
        return 0.0  # 无法比较时视为不相似，保留两者
    return len(sa & sb) / len(sa | sb)


class DiversityFilter:
    """
    基于 n-gram Jaccard 相似度的内容多样性过滤器（纯 Python，无额外依赖）

    解决问题：搜索结果中常出现同一话题的相似内容（如多个来源转载同一新闻），
    导致 LLM 浪费 token 处理重复信息，且来源看似多样实则单一。

    方法：贪心选择
      1. 先选 score 最高的结果（已由 ResultFilter 保证按 score 降序）
      2. 遍历剩余结果，与已选集合的最高相似度 < sim_threshold 才加入
      3. 最多返回 target_k 条
    """

    @staticmethod
    def select(
        results: list[dict],
        target_k: int = 5,
        sim_threshold: float = 0.45,
    ) -> list[dict]:
        if len(results) <= target_k:
            return results

        selected = [results[0]]
        for r in results[1:]:
            if len(selected) >= target_k:
                break
            content = r.get("content", "")
            max_sim = max(
                _ngram_jaccard(content, s.get("content", ""))
                for s in selected
            )
            if max_sim < sim_threshold:
                selected.append(r)

        return selected


def _days_to_ddg_timelimit(days: int | None) -> str | None:
    """将天数转换为 DuckDuckGo timelimit 参数（'d'/'w'/'m'/'y'）"""
    if not days:
        return None
    if days <= 1:
        return "d"
    if days <= 7:
        return "w"
    if days <= 31:
        return "m"
    return "y"


class _DuckDuckGoBackend:
    """DuckDuckGo 免费搜索后端（无需 API Key，通过线程池运行同步库）"""

    async def search(self, query: str, max_results: int = 8, days: int | None = None) -> list[dict]:
        try:
            from duckduckgo_search import DDGS

            loop = asyncio.get_event_loop()
            timelimit = _days_to_ddg_timelimit(days)

            def _sync() -> list[dict]:
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=max_results, timelimit=timelimit))

            raw = await loop.run_in_executor(None, _sync)
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "content": r.get("body", ""),
                    "score": 0.5,
                    "source": "duckduckgo",
                    "published_date": "",
                }
                for r in raw
            ]
        except ImportError:
            _logger.warning("[DuckDuckGo] duckduckgo-search 未安装，请执行: pip install duckduckgo-search")
            return []
        except Exception as e:
            _logger.error("[DuckDuckGo] 搜索失败: %s", e)
            return []

    async def news_search(self, query: str, max_results: int = 8, days: int | None = None) -> list[dict]:
        try:
            from duckduckgo_search import DDGS

            loop = asyncio.get_event_loop()
            timelimit = _days_to_ddg_timelimit(days)

            def _sync() -> list[dict]:
                with DDGS() as ddgs:
                    return list(ddgs.news(query, max_results=max_results, timelimit=timelimit))

            raw = await loop.run_in_executor(None, _sync)
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("body", ""),
                    "score": 0.5,
                    "source": "duckduckgo_news",
                    "published_date": r.get("date", ""),
                }
                for r in raw
            ]
        except ImportError:
            _logger.warning("[DuckDuckGo] duckduckgo-search 未安装")
            return []
        except Exception as e:
            _logger.error("[DuckDuckGo] 新闻搜索失败: %s", e)
            return []


class WebSearchTool:
    """
    搜索工具主类

    Fallback 策略：
      async_search / async_news_search：Tavily → DuckDuckGo
      search（同步）：仅 Tavily，失败返回空列表
    """

    def __init__(self):
        self._tavily_client = None
        self._tavily_async = None
        self._ddg = _DuckDuckGoBackend()
        self._cache = SearchCache()

        if config.TAVILY_API_KEY:
            try:
                from tavily import TavilyClient, AsyncTavilyClient
                self._tavily_client = TavilyClient(api_key=config.TAVILY_API_KEY)
                self._tavily_async = AsyncTavilyClient(api_key=config.TAVILY_API_KEY)
            except Exception as e:
                _logger.warning("[WebSearch] Tavily 初始化失败，将使用 DuckDuckGo: %s", e)

    # ── 异步搜索（主入口）────────────────────────────────────────────

    async def async_search(
        self, query: str, max_results: int = 5, search_depth: str = "basic",
        require_keyword: str = "", days: int | None = None,
        include_domains: list[str] | None = None,
    ) -> list[dict]:
        """通用异步搜索，优先 Tavily，失败自动切换 DuckDuckGo。
        days: 只返回最近 N 天内的结果（None = 不限制）
        include_domains: 只从这些域名返回结果（仅 Tavily 支持）"""

        # ── 缓存命中检查 ─────────────────────────────────────────────
        cache_key = SearchCache.make_key(query, "general", days, include_domains)
        cached = self._cache.get(cache_key)
        if cached is not None:
            filtered = ResultFilter.filter(cached, require_keyword=require_keyword)
            diverse = DiversityFilter.select(filtered, target_k=max_results)
            _logger.debug("[WebSearch:cache-hit] %d 条 | %s", len(diverse), query[:50])
            return diverse

        # ── 真实搜索 ─────────────────────────────────────────────────
        raw: list[dict] = []
        backend = "none"

        if self._tavily_async:
            try:
                params: dict = dict(
                    query=query,
                    max_results=max_results + 3,
                    search_depth=search_depth,
                    include_answer=True,
                )
                if days:
                    params["days"] = days
                if include_domains:
                    params["include_domains"] = include_domains
                resp = await self._tavily_async.search(**params)
                raw = resp.get("results", [])
                backend = "tavily"
            except Exception as e:
                _logger.warning("[WebSearch] Tavily 失败 → 切换 DuckDuckGo: %s", e)

        if not raw:
            raw = await self._ddg.search(query, max_results=max_results + 3, days=days)
            backend = "duckduckgo"

        self._cache.set(cache_key, query, raw)   # 写入缓存（空结果自动跳过）

        filtered = ResultFilter.filter(raw, require_keyword=require_keyword)
        diverse = DiversityFilter.select(filtered, target_k=max_results)
        days_label = f" ≤{days}天" if days else ""
        _logger.info("[WebSearch:%s%s] %d → 质量%d → 多样%d 条 | %s",
                     backend, days_label, len(raw), len(filtered), len(diverse), query[:50])
        return diverse

    async def async_news_search(
        self, query: str, max_results: int = 5, require_keyword: str = "",
        days: int = 90,
    ) -> list[dict]:
        """新闻搜索，优先 Tavily，失败自动切换 DuckDuckGo。
        days: 默认 90 天（覆盖产品演化轨迹所需的 3 个月范围）"""

        # ── 缓存命中检查 ─────────────────────────────────────────────
        cache_key = SearchCache.make_key(query, "news", days, None)
        cached = self._cache.get(cache_key)
        if cached is not None:
            filtered = ResultFilter.filter(cached, require_keyword=require_keyword)
            diverse = DiversityFilter.select(filtered, target_k=max_results)
            _logger.debug("[WebSearch:cache-hit-news] %d 条 | %s", len(diverse), query[:50])
            return diverse

        # ── 真实搜索 ─────────────────────────────────────────────────
        raw: list[dict] = []
        backend = "none"

        if self._tavily_async:
            try:
                resp = await self._tavily_async.search(
                    query=query,
                    max_results=max_results + 3,
                    search_depth="basic",
                    topic="news",
                    include_answer=True,
                    days=days,
                )
                raw = resp.get("results", [])
                backend = "tavily_news"
            except Exception as e:
                _logger.warning("[WebSearch] Tavily 新闻失败 → 切换 DuckDuckGo: %s", e)

        if not raw:
            raw = await self._ddg.news_search(query, max_results=max_results + 3, days=days)
            backend = "duckduckgo_news"

        self._cache.set(cache_key, query, raw)   # 写入缓存（空结果自动跳过）

        filtered = ResultFilter.filter(raw, require_keyword=require_keyword)
        diverse = DiversityFilter.select(filtered, target_k=max_results)
        _logger.info("[WebSearch:%s ≤%d天] %d → 质量%d → 多样%d 条 | %s",
                     backend, days, len(raw), len(filtered), len(diverse), query[:50])
        return diverse

    # ── 同步搜索（兼容性保留）────────────────────────────────────────

    def search(self, query: str, max_results: int = 5, search_depth: str = "basic") -> list[dict]:
        """同步搜索，仅 Tavily（app_store.py 等同步场景使用）"""
        if self._tavily_client:
            try:
                resp = self._tavily_client.search(
                    query=query,
                    max_results=max_results + 3,
                    search_depth=search_depth,
                    include_answer=True,
                )
                raw = resp.get("results", [])
                return ResultFilter.filter(raw)[:max_results]
            except Exception as e:
                _logger.warning("[WebSearch] Tavily 同步失败: %s", e)
        return []

    # ── 格式化输出 ───────────────────────────────────────────────────

    @staticmethod
    def format_results(results: list[dict]) -> str:
        """将搜索结果格式化为 LLM 可读文本，附来源标记、发布日期和相关性评分"""
        if not results:
            return "未找到相关结果"
        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "无标题")
            url = r.get("url", "")
            content = r.get("content", "")[:400]
            score = r.get("score", 0)
            source = r.get("source", "tavily")
            # 发布日期（取前 10 字符：YYYY-MM-DD）
            pub_date = (r.get("published_date") or r.get("date") or "").strip()[:10]
            date_part = f"   发布日期: {pub_date}\n" if pub_date else ""
            lines.append(
                f"{i}. **{title}** [{source}]\n"
                f"   URL: {url}\n"
                f"{date_part}"
                f"   摘要: {content}\n"
                f"   相关性: {score:.2f}\n"
            )
        return "\n".join(lines)
