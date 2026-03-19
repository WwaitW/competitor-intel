"""
key_validator.py — API Key 实时预检验证（#33）

在用户填入 API Key 后，发送最小代价请求验证有效性：
  - OpenRouter：GET /api/v1/models（不消耗 Token，仅验证认证）
  - Tavily    ：POST /search，1 条结果（消耗 1 次配额，但最低限度）

全部使用标准库 urllib，无额外依赖。
返回 (ok: bool, message: str)：
  ok=True  → Key 有效，message 含附加信息（如可用模型数）
  ok=False → Key 无效或网络错误，message 含具体原因
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error


def validate_openrouter(api_key: str, timeout: int = 8) -> tuple[bool, str]:
    """
    调用 OpenRouter /api/v1/models 接口验证 Key 有效性。
    成功时返回可用模型数量；失败时返回 HTTP 状态码或网络错误。
    """
    if not api_key or not api_key.strip():
        return False, "Key 为空"

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            model_count = len(data.get("data", []))
            return True, f"Key 有效，可访问 {model_count} 个模型"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Key 无效（401 Unauthorized）"
        if e.code == 403:
            return False, "Key 无权限（403 Forbidden）"
        return False, f"HTTP 错误 {e.code}"
    except urllib.error.URLError as e:
        return False, f"网络错误：{e.reason}"
    except Exception as e:
        return False, f"验证失败：{e}"


def validate_tavily(api_key: str, timeout: int = 10) -> tuple[bool, str]:
    """
    调用 Tavily /search 接口验证 Key 有效性（最小查询，1 条结果）。
    成功时返回确认信息；失败时返回具体原因。
    """
    if not api_key or not api_key.strip():
        return False, "Key 为空"

    payload = json.dumps({
        "api_key": api_key.strip(),
        "query": "test",
        "max_results": 1,
        "search_depth": "basic",
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            result_count = len(data.get("results", []))
            return True, f"Key 有效（返回 {result_count} 条结果）"
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:120]
        except Exception:
            pass
        if e.code == 401:
            return False, "Key 无效（401 Unauthorized）"
        if e.code == 400:
            # 400 无法确定 Key 本身是否有效，保守处理：提示用户检查格式
            if "invalid api" in body.lower() or "unauthorized" in body.lower():
                return False, f"Key 无效：{body}"
            return False, f"Key 格式可能有误（HTTP 400），请确认已完整复制"
        return False, f"HTTP 错误 {e.code}：{body}"
    except urllib.error.URLError as e:
        return False, f"网络错误：{e.reason}"
    except Exception as e:
        return False, f"验证失败：{e}"
