"""
matrix_report.py — 批量竞品对比矩阵报告生成器（P5.2）

职责：
  将多份单竞品 data dict 聚合为一份横向对比报告：
  ① 总览对比矩阵表（N 竞品 × M 维度）
  ② 各竞品独立摘要（可展开）

公共接口：
  MatrixReportGenerator.generate(results: list[dict], our_product: str = "") -> str
    → Markdown 字符串

  MatrixReportGenerator.to_html(md: str) -> str
    → HTML 字符串（复用 ReportGenerator.to_html）
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional


# ── 维度提取辅助 ──────────────────────────────────────────────────────────

def _extract_pricing(data: dict) -> str:
    """从 research summary 或 analysis 里提取定价信息（关键词匹配）"""
    text = ""
    if data.get("research"):
        text += data["research"].get("summary", "")
    if data.get("analysis"):
        text += data["analysis"].get("analysis", "")

    # 查找 $数字 或 免费 / Free / 定价 等关键词附近文字
    patterns = [
        r'\$[\d,]+(?:\.\d+)?(?:/月|/mo|/month|/年|/yr|/year)?',
        r'¥[\d,]+(?:\.\d+)?(?:/月|/年)?',
        r'(?:免费|Free|Freemium|free tier)',
        r'(?:按需付费|Pay-as-you-go|Pay as you go)',
    ]
    found = []
    for pat in patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        found.extend(matches[:2])

    if found:
        return "、".join(dict.fromkeys(found))  # 去重保序

    # 兜底：截取 analysis 前 80 字符中含"价"的句子
    for line in text.split("\n"):
        if any(kw in line for kw in ["价格", "定价", "收费", "price", "pricing", "plan"]):
            snippet = line.strip()[:60]
            if snippet:
                return snippet
    return "—"


def _extract_score(data: dict) -> str:
    eval_result = data.get("evaluation") or {}
    score = eval_result.get("score")
    if score is not None:
        passed = eval_result.get("passed", True)
        suffix = " ✓" if passed else " ⚠"
        return f"{score}/10{suffix}"
    return "—"


def _extract_funding(data: dict) -> str:
    """从 analysis 里提取融资信息"""
    analysis = (data.get("analysis") or {}).get("analysis", "")
    for line in analysis.split("\n"):
        if any(kw in line for kw in ["融资", "融了", "Series", "估值", "IPO", "上市", "收购"]):
            snippet = line.strip()[:60]
            if snippet:
                return snippet
    return "—"


def _extract_highlights(data: dict) -> str:
    """从 strategy 里提取 1~2 条核心优势（SWOT 优势部分）"""
    strategy = (data.get("strategy") or {}).get("strategy", "")
    lines = [l.strip() for l in strategy.split("\n") if l.strip()]
    # 取 "优势" 或 "Strength" 之后的第一个 bullet
    in_strength = False
    bullets = []
    for line in lines:
        if re.search(r"(优势|Strength|S[Ww][Oo][Tt])", line):
            in_strength = True
            continue
        if in_strength and line.startswith(("-", "•", "*", "+")):
            bullets.append(re.sub(r'^[-•*+]\s*', '', line)[:50])
            if len(bullets) >= 2:
                break
        elif in_strength and re.search(r"(劣势|Weakness|机会|Opportunit|威胁|Threat)", line):
            break
    return "；".join(bullets) if bullets else "—"


def _extract_recommendation(data: dict) -> str:
    """
    从 strategy 执行摘要中提取「优先行动」作为综合推荐结论。
    兜底逻辑：取战略建议第一条，再兜底取威胁描述。
    """
    strategy = (data.get("strategy") or {}).get("strategy", "")

    # 1. 优先：执行摘要的「优先行动」
    m = re.search(r'[*_]?优先行动[*_]?[：:]\s*\*?\*?\[?(.+?)(?:\]|\n|$)', strategy)
    if m:
        text = m.group(1).strip().strip("*_[]")
        if len(text) > 5:
            return text[:70]

    # 2. 次选：战略建议第一条（数字开头）
    in_strategy = False
    for line in strategy.split("\n"):
        stripped = line.strip()
        if re.search(r"##\s*战略建议", stripped):
            in_strategy = True
            continue
        if in_strategy and re.match(r'^[1１][\.\、\)）]', stripped):
            clean = re.sub(r'^[1１][\.\、\)） ]+', '', stripped)
            if len(clean) > 5:
                return clean[:70]
        if in_strategy and re.match(r'^##', stripped):
            break

    # 3. 兜底
    return "—"


def _safe_summary(data: dict, max_chars: int = 120) -> str:
    research = data.get("research") or {}
    summary = research.get("summary", "")
    if not summary:
        return "—"
    # 取第一段或前 max_chars 字
    first_para = summary.split("\n\n")[0].strip()
    return first_para[:max_chars] + ("…" if len(first_para) > max_chars else "")


# ── 矩阵生成 ────────────────────────────────────────────────────────────

class MatrixReportGenerator:

    # 对比矩阵行定义：(行标题, 提取函数)
    _MATRIX_ROWS: list[tuple[str, callable]] = [
        ("定价",     _extract_pricing),
        ("融资情况", _extract_funding),
        ("核心优势", _extract_highlights),
        ("数据质量", _extract_score),
        ("综合推荐", _extract_recommendation),   # #28：结论行
    ]

    @classmethod
    def generate(
        cls,
        results: list[dict],
        our_product: str = "",
    ) -> str:
        """
        生成批量竞品对比 Markdown 报告。
        results: list[dict]，每个元素是 Orchestrator.run() 或 run_batch() 的单竞品输出。
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        competitors = [r["competitor"] for r in results]
        valid = [r for r in results if not r.get("error")]

        lines: list[str] = []

        # ── 报告头 ──────────────────────────────────────────
        lines.append(f"# 批量竞品对比报告")
        lines.append(f"\n> 生成时间：{now}  |  竞品数量：{len(competitors)}  |  我方产品：{our_product or '—'}")
        lines.append("")

        if not valid:
            lines.append("⚠️ 所有竞品分析均失败，无法生成对比报告。")
            return "\n".join(lines)

        # ── 错误提示 ──────────────────────────────────────
        errors = [r for r in results if r.get("error")]
        if errors:
            lines.append("**⚠️ 以下竞品分析失败（已排除出矩阵）：**")
            for r in errors:
                lines.append(f"- `{r['competitor']}`：{r['error'][:100]}")
            lines.append("")

        # ── 横向对比矩阵 ──────────────────────────────────
        lines.append("## 横向对比矩阵")
        lines.append("")

        # 表头
        header = "| 维度 | " + " | ".join(f"**{r['competitor']}**" for r in valid) + " |"
        sep    = "| --- | " + " | ".join(":---:" for _ in valid) + " |"
        lines.append(header)
        lines.append(sep)

        for row_name, extractor in cls._MATRIX_ROWS:
            cells = []
            for r in valid:
                try:
                    cell_text = str(extractor(r)).replace("|", "｜").replace("\n", " ")
                except Exception:
                    cell_text = "—"
                # 「综合推荐」行加粗，视觉突出
                cells.append(f"**{cell_text}**" if row_name == "综合推荐" else cell_text)
            lines.append(f"| {row_name} | " + " | ".join(cells) + " |")

        # 公司概况行
        lines.append(
            "| 公司概况 | "
            + " | ".join(
                _safe_summary(r, max_chars=80).replace("|", "｜").replace("\n", " ")
                for r in valid
            )
            + " |"
        )
        lines.append("")
        lines.append("> 💡 **综合推荐** 行提取自各竞品执行摘要「优先行动」，代表针对该竞品最值得立即执行的应对策略。")
        lines.append("")

        # ── 功能对比矩阵（汇总每个竞品的 feature_matrix） ──
        lines.append("## 功能对比矩阵")
        lines.append("")
        lines.append("*以下各竞品的功能矩阵来自独立分析，供横向参考：*")
        lines.append("")

        for r in valid:
            product = r.get("product") or {}
            fm = product.get("feature_matrix", "")
            if fm:
                lines.append(f"### {r['competitor']}")
                lines.append(fm.strip())
                lines.append("")

        # ── 各竞品独立摘要 ────────────────────────────────
        lines.append("## 各竞品详细摘要")
        lines.append("")

        for r in valid:
            c = r["competitor"]
            lines.append(f"### {c}")

            research  = r.get("research")  or {}
            analysis  = r.get("analysis")  or {}
            strategy  = r.get("strategy")  or {}
            meta      = r.get("meta")      or {}

            if research.get("summary"):
                lines.append("**公司概况**")
                lines.append(research["summary"][:400].strip())
                lines.append("")

            if analysis.get("analysis"):
                lines.append("**业务分析**")
                lines.append(analysis["analysis"][:300].strip())
                lines.append("")

            if strategy.get("strategy"):
                lines.append("**SWOT & 战略建议**")
                lines.append(strategy["strategy"][:400].strip())
                lines.append("")

            elapsed = meta.get("elapsed_seconds", "—")
            tokens  = meta.get("total_tokens", 0)
            cost    = meta.get("estimated_cost_usd", "—")
            lines.append(
                f"*耗时 {elapsed}s | Token: {tokens:,} | 成本: ${cost}*"
                if isinstance(tokens, int) else
                f"*耗时 {elapsed}s*"
            )
            lines.append("")
            lines.append("---")
            lines.append("")

        # ── 我方产品战略建议（如有） ─────────────────────
        if our_product and valid:
            lines.append("## 综合战略建议")
            lines.append("")
            lines.append(
                f"基于以上 {len(valid)} 个竞品的分析，结合我方产品「{our_product}」的定位，"
                "建议重点关注以下差距："
            )
            lines.append("")
            for r in valid:
                strategy = (r.get("strategy") or {}).get("strategy", "")
                # 提取战略建议（以数字或 bullet 开头的行）
                bullets = [
                    re.sub(r'^[\d\.\-•*+]\s*', '', l).strip()
                    for l in strategy.split("\n")
                    if re.match(r'^[\d\.\-•*+]', l.strip()) and len(l.strip()) > 10
                ][:2]
                if bullets:
                    lines.append(f"**针对 {r['competitor']}**：")
                    for b in bullets:
                        lines.append(f"- {b[:80]}")
                    lines.append("")

        lines.append(f"*报告由 Intelix 自动生成 · {now}*")

        return "\n".join(lines)

    @classmethod
    def to_html(cls, md: str) -> str:
        """复用 ReportGenerator 的 HTML 转换逻辑"""
        from core.report import ReportGenerator
        return ReportGenerator.to_html(md)
