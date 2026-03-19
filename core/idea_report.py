"""
idea_report.py — 想法解析最终报告生成器

流程：
  1. 调用 MatrixReportGenerator.generate() 生成竞品矩阵部分
  2. 从 batch_results 提取各竞品摘要（~800字/竞品）
  3. 一次 LLM 调用 (idea_strategist.txt)，生成 4 章节综合分析
  4. 组装最终 Markdown 报告

公共接口：
  IdeaReportGenerator.generate(
      idea_context: dict,   # IdeaParserAgent 输出
      batch_results: list,  # Orchestrator.run_batch() 输出
      our_product: str = "",
      model: str = "",
      progress_callback = None,
  ) -> str  # Markdown 字符串
"""
from __future__ import annotations

import os
from datetime import datetime

from openai import AsyncOpenAI

import config
from core.llm_retry import llm_call_with_retry
from core.matrix_report import MatrixReportGenerator


def _extract_competitor_summary(result: dict, max_chars: int = 800) -> str:
    """从单竞品分析结果提取约 max_chars 字的摘要文本"""
    c = result.get("competitor", "未知")
    parts = [f"### {c}"]

    research = result.get("research") or {}
    if research.get("summary"):
        parts.append(research["summary"][:300].strip())

    analysis = result.get("analysis") or {}
    if analysis.get("analysis"):
        parts.append(analysis["analysis"][:250].strip())

    strategy = result.get("strategy") or {}
    if strategy.get("strategy"):
        parts.append(strategy["strategy"][:250].strip())

    text = "\n\n".join(parts)
    return text[:max_chars]


class IdeaReportGenerator:
    """将想法解析 + 竞品分析结果组合为以「市场验证」为重点的最终报告"""

    @classmethod
    async def generate(
        cls,
        idea_context: dict,
        batch_results: list,
        our_product: str = "",
        model: str = "",
        progress_callback=None,
    ) -> str:
        """
        生成想法解析综合报告。

        参数：
            idea_context     — IdeaParserAgent.run() 的返回值
            batch_results    — Orchestrator.run_batch() 的返回值列表
            our_product      — 用户自己的产品名（可选）
            model            — 使用的 LLM 模型名（空则用默认）
            progress_callback — 异步进度回调

        返回：Markdown 字符串
        """
        _model = model or config.DEFAULT_MODEL
        llm = AsyncOpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
        )

        # ── Step 1: 竞品矩阵 ────────────────────────────────────────────
        if progress_callback:
            await progress_callback("📊 生成竞品对比矩阵...")

        matrix_md = MatrixReportGenerator.generate(batch_results, our_product=our_product)

        # ── Step 2: 拼接竞品摘要供 LLM 使用 ────────────────────────────
        valid_results = [r for r in batch_results if not r.get("error")]
        competitor_summaries = "\n\n---\n\n".join(
            _extract_competitor_summary(r) for r in valid_results
        )

        # ── Step 3: LLM 综合分析 ────────────────────────────────────────
        if progress_callback:
            await progress_callback("🤔 AI 正在综合分析市场机会...")

        prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/idea_strategist.txt")
        with open(prompt_path, encoding="utf-8") as f:
            system_prompt = f.read()

        user_msg = cls._build_user_message(idea_context, competitor_summaries, our_product)

        response = await llm_call_with_retry(
            llm,
            model=_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=2000,
        )

        strategic_analysis = response.choices[0].message.content.strip()

        # ── Step 4: 组装最终报告 ─────────────────────────────────────────
        if progress_callback:
            await progress_callback("📝 组装最终报告...")

        return cls._assemble_report(idea_context, matrix_md, strategic_analysis, our_product)

    @classmethod
    def _build_user_message(
        cls,
        idea_context: dict,
        competitor_summaries: str,
        our_product: str,
    ) -> str:
        lines = ["## 用户想法"]
        lines.append(f"**核心定位**：{idea_context.get('idea_summary', '')}")
        lines.append(f"**目标用户**：{idea_context.get('target_users', '')}")
        lines.append(f"**核心价值**：{idea_context.get('core_value', '')}")
        lines.append(f"**解决问题**：{idea_context.get('key_problem', '')}")
        if our_product:
            lines.append(f"**产品名称**：{our_product}")

        lines.append("")
        lines.append("## 竞品分析摘要")
        lines.append(competitor_summaries[:4000])  # 避免超出 context

        lines.append("")
        lines.append("请基于以上信息，生成市场验证报告（严格按照 4 个章节输出 Markdown）。")
        return "\n".join(lines)

    @classmethod
    def _assemble_report(
        cls,
        idea_context: dict,
        matrix_md: str,
        strategic_analysis: str,
        our_product: str,
    ) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        title = our_product or idea_context.get("idea_summary", "产品想法")
        keywords = idea_context.get("market_keywords", [])

        lines = []

        # ── 报告头 ───────────────────────────────────────────────────────
        lines.append(f"# 💡 想法解析报告：{title}")
        lines.append(f"\n> 生成时间：{now}  |  由 Intelix 自动分析")
        lines.append("")

        # ── 想法解析摘要卡片 ─────────────────────────────────────────────
        lines.append("## 你的想法")
        lines.append("")
        if idea_context.get("idea_summary"):
            lines.append(f"> **{idea_context['idea_summary']}**")
            lines.append("")

        info_table_rows = []
        if idea_context.get("target_users"):
            info_table_rows.append(("🎯 目标用户", idea_context["target_users"]))
        if idea_context.get("core_value"):
            info_table_rows.append(("✨ 核心价值", idea_context["core_value"]))
        if idea_context.get("key_problem"):
            info_table_rows.append(("🔍 解决问题", idea_context["key_problem"]))

        if info_table_rows:
            lines.append("| 维度 | 内容 |")
            lines.append("| --- | --- |")
            for dim, content in info_table_rows:
                lines.append(f"| {dim} | {content} |")
            lines.append("")

        if keywords:
            lines.append(f"**市场关键词**：{'  '.join(f'`{k}`' for k in keywords)}")
            lines.append("")

        lines.append("---")
        lines.append("")

        # ── 竞品矩阵（来自 MatrixReportGenerator）─────────────────────────
        # 截取矩阵部分（去掉 matrix 的报告头，直接追加章节）
        matrix_body = _strip_matrix_header(matrix_md)
        lines.append(matrix_body)
        lines.append("")
        lines.append("---")
        lines.append("")

        # ── 综合战略分析（LLM 生成的 4 章节）───────────────────────────────
        lines.append("# 市场验证分析")
        lines.append("")
        lines.append(strategic_analysis)
        lines.append("")

        # ── 报告尾 ───────────────────────────────────────────────────────
        lines.append("---")
        lines.append("")
        lines.append(f"*本报告由 Intelix 自动生成 · {now}*")

        return "\n".join(lines)


def _strip_matrix_header(matrix_md: str) -> str:
    """去除矩阵报告的 h1 标题行，保留其余内容"""
    lines = matrix_md.splitlines()
    # 跳过以 "# " 开头的第一行标题和紧随的空行/meta 行
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            start = i + 1
            # 跳过紧跟的 blockquote meta 行
            while start < len(lines) and (
                lines[start].strip() == "" or lines[start].startswith(">")
            ):
                start += 1
            break
    return "\n".join(lines[start:])
