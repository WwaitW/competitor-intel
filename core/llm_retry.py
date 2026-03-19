"""
llm_retry.py — LLM 调用自动重试（#34）

解决问题：OpenRouter 及下游模型在网络抖动、限流时偶发失败，
          一次性调用无容错，导致整个分析流程中断。

策略：指数退避重试（Exponential Backoff）
  - 最多重试 max_retries 次（默认 3），共最多 4 次尝试
  - 退避间隔：base_delay * (2 ** attempt)  → 2s、4s、8s
  - 可重试错误：网络/超时/限流(429)/服务器错误(5xx)
  - 不重试错误：认证失败(401)、请求错误(400)

用法（替换各 Agent 中的直接 LLM 调用）：
    # 原来
    response = await self.llm.chat.completions.create(**params)
    # 现在
    from core.llm_retry import llm_call_with_retry
    response = await llm_call_with_retry(self.llm, **params)
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# 可重试的 openai 异常类名（字符串判断，避免 import 时依赖版本）
_RETRYABLE_TYPES = {
    "RateLimitError",        # 429 限流
    "APIConnectionError",    # 网络连接失败
    "APITimeoutError",       # 超时
    "InternalServerError",   # 500/503 服务端错误
    "ServiceUnavailableError",
}

# 不重试的异常类名（直接抛出）
_FATAL_TYPES = {
    "AuthenticationError",   # 401 Key 无效
    "PermissionDeniedError", # 403
    "BadRequestError",       # 400 请求参数问题
    "NotFoundError",         # 404
}


def _is_retryable(exc: Exception) -> bool:
    """根据异常类型名称判断是否可重试"""
    exc_type = type(exc).__name__
    if exc_type in _FATAL_TYPES:
        return False
    if exc_type in _RETRYABLE_TYPES:
        return True
    # 兜底：其余 openai 异常（如 APIStatusError 子类）按 HTTP 状态码判断
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status in (429, 500, 502, 503, 504)
    # 非 openai 异常（如 network OSError）也重试
    return True


async def llm_call_with_retry(
    client,
    max_retries: int = 3,
    base_delay: float = 2.0,
    **kwargs,
):
    """
    带指数退避重试的 LLM 调用封装。

    参数：
        client       — AsyncOpenAI 实例（self.llm）
        max_retries  — 最大重试次数（默认 3，共最多 4 次尝试）
        base_delay   — 首次重试等待秒数（默认 2s，后续翻倍：2、4、8）
        **kwargs     — 直接透传给 client.chat.completions.create()

    返回：
        openai ChatCompletion 响应对象

    异常：
        最终仍失败时抛出最后一次异常。
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await client.chat.completions.create(**kwargs)

        except Exception as exc:
            last_exc = exc

            if not _is_retryable(exc):
                # 不可重试错误（认证/参数问题），直接抛出
                logger.error("[LLMRetry] 不可重试错误 %s: %s", type(exc).__name__, exc)
                raise

            if attempt >= max_retries:
                # 已达最大重试次数
                logger.error(
                    "[LLMRetry] 已达最大重试次数 (%d)，放弃。最后错误: %s",
                    max_retries, exc,
                )
                raise

            delay = base_delay * (2 ** attempt)
            logger.warning(
                "[LLMRetry] 第 %d/%d 次重试，等待 %.1fs。原因: %s(%s)",
                attempt + 1, max_retries, delay, type(exc).__name__, exc,
            )
            await asyncio.sleep(delay)

    raise last_exc  # 理论上不会到达，兜底
