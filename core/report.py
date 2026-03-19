"""
report.py — 结构化报告生成器

P2.2 架构升级：引入 IR（中间表示）模式
  原来：各 Agent 输出 → 字符串拼接 → Markdown
  现在：各 Agent 输出 → IRDocument（结构化） → validate() → to_markdown()

IRDocument 职责：
  1. 将松散的 agent 输出映射为有意义的章节对象（ReportSection）
  2. 校验每个章节内容是否达到最低长度（is_thin 检测）
  3. 渲染为最终 Markdown（内化质量徽章逻辑）
  4. to_dict() 序列化，便于调试或结构化存储

ReportGenerator 的外部接口（generate / to_html）保持不变。
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

from core.logger import get_logger

_logger = get_logger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────────────

@dataclass
class ReportSection:
    """报告中的一个独立章节"""
    section_id: str       # 机器可读的唯一 ID
    title: str            # 展示用标题（含序号）
    content: str          # Markdown 正文
    source_agent: str     # 产生该内容的 Agent 名称
    min_chars: int = 100  # 最低内容长度（用于 validate）

    @property
    def char_count(self) -> int:
        return len(self.content.strip())

    def is_thin(self) -> bool:
        """内容是否不足最低长度要求"""
        return self.char_count < self.min_chars


@dataclass
class IRDocument:
    """
    报告的中间表示（Intermediate Representation）

    持有结构化的章节列表，支持校验和多格式渲染。
    实例通过 IRDocument.from_agent_outputs(data) 构建。
    """
    competitor: str
    our_product: str
    sections: list          # list[ReportSection]
    meta: dict
    evaluation: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)   # [{id, title, url}, ...]
    generated_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
    )

    # ── 构建 ─────────────────────────────────────────────────────────

    @classmethod
    def from_agent_outputs(cls, data: dict) -> "IRDocument":
        """从 orchestrator 返回的 data 字典构建 IRDocument"""
        research = data["research"]
        analysis = data["analysis"]
        product = data["product"]
        strategy = data["strategy"]

        sections = [
            ReportSection(
                section_id="company_overview",
                title="1. 公司概况与产品调研",
                content=research["summary"],
                source_agent="researcher",
                min_chars=200,
            ),
            ReportSection(
                section_id="business_analysis",
                title="2. 业务分析（融资 / 营收 / 近期事件）",
                content=analysis["analysis"],
                source_agent="analyst",
                min_chars=150,
            ),
            ReportSection(
                section_id="feature_matrix",
                title="3. 核心功能对比矩阵",
                content=product["feature_matrix"],
                source_agent="product",
                min_chars=100,
            ),
            ReportSection(
                section_id="user_reviews",
                title="4. 用户评价分析（G2 / Capterra / 用户痛点信号）",
                content=(
                    f"> 数据来源：G2、Capterra、TrustRadius、ProductHunt 及用户抱怨信号\n\n"
                    f"### 原始评价摘要\n{research['reviews_info'][:2500]}\n\n"
                    f"> 高频好评 / 差评提炼详见第 6 章「用户核心痛点 TOP3」"
                ),
                source_agent="researcher",
                min_chars=80,
            ),
            ReportSection(
                section_id="market_dynamics",
                title="5. 市场动态（近30天）",
                content=(
                    f"### 新闻动态\n{research['news_info'][:1200]}\n\n"
                    f"### 招聘信号\n{research['hiring_info'][:800]}"
                ),
                source_agent="researcher",
                min_chars=80,
            ),
            ReportSection(
                section_id="swot_strategy",
                title="6. SWOT 分析与战略建议",
                content=strategy["strategy"],
                source_agent="strategist",
                min_chars=200,
            ),
        ]

        # 收集来源（来自 researcher 的 sources 字段）
        research_sources = (data["research"] or {}).get("sources", [])

        return cls(
            competitor=data["competitor"],
            our_product=data.get("our_product", ""),
            sections=sections,
            meta=data["meta"],
            evaluation=data.get("evaluation", {}),
            sources=research_sources,
        )

    # ── 校验 ─────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """
        检查各章节内容是否满足最低长度要求。
        返回警告字符串列表；列表为空表示全部通过。
        """
        return [
            f"章节「{s.title}」内容不足（{s.char_count} / {s.min_chars} 字符）"
            for s in self.sections
            if s.is_thin()
        ]

    # ── 执行摘要提取 ──────────────────────────────────────────────────

    def _extract_exec_summary(self) -> str:
        """从 strategist 输出中提取 ## ⚡ 执行摘要 块"""
        for section in self.sections:
            if section.section_id == "swot_strategy":
                m = re.search(
                    r'(##\s*⚡\s*执行摘要.*?)(?=\n##|\Z)',
                    section.content,
                    re.DOTALL,
                )
                if m:
                    return m.group(1).strip()
        return ""

    # ── 渲染 ─────────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        """渲染为最终 Markdown 报告字符串"""
        elapsed = self.meta.get("elapsed_seconds", 0)
        cost = self.meta.get("estimated_cost_usd", 0)
        tokens = self.meta.get("total_tokens", 0)

        # 质量评分徽章
        eval_score = self.evaluation.get("score")
        eval_passed = self.evaluation.get("passed", True)
        eval_gaps = self.evaluation.get("gaps", [])

        if eval_score is not None:
            if eval_passed:
                quality_badge = f"质量评分：{eval_score}/10 ✓"
            else:
                quality_badge = (
                    f"质量评分：{eval_score}/10 → 已补充（{'、'.join(eval_gaps)}）"
                )
            quality_line = f" | {quality_badge}"
        else:
            quality_line = ""

        our_product_line = f" vs {self.our_product}" if self.our_product else ""

        lines = [
            f"# 竞品分析报告：{self.competitor}{our_product_line}",
            "",
            (
                f"> 生成时间：{self.generated_at} | 分析耗时：{elapsed}s"
                f" | Token 消耗：{tokens:,} | 估算成本：${cost}{quality_line}"
            ),
            "",
            "---",
        ]

        # ── 执行摘要（置于报告顶部，30秒速读版）────────────────────
        exec_summary = self._extract_exec_summary()
        if exec_summary:
            lines += ["", exec_summary, "", "---"]

        for section in self.sections:
            lines += ["", f"## {section.title}", "", section.content, "", "---"]

        # 参考来源章节
        if self.sources:
            lines += ["", "## 参考来源", ""]
            for s in self.sources:
                lines.append(f"- [{s['id']}] [{s['title']}]({s['url']})")
            lines.append("")

        # 薄章节警告附在报告底部（不影响正文阅读）
        thin = [s for s in self.sections if s.is_thin()]
        if thin:
            thin_names = "、".join(s.title for s in thin)
            lines += ["", f"> ⚠️ 数据不足章节：{thin_names}（可能影响分析质量）"]

        lines += [
            "",
            "*本报告由 Intelix 自动生成，数据来源于公开网络信息，仅供参考。*",
        ]

        return "\n".join(lines)

    # ── 序列化 ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为字典，便于调试或结构化存储"""
        return {
            "competitor": self.competitor,
            "our_product": self.our_product,
            "generated_at": self.generated_at,
            "meta": self.meta,
            "evaluation": self.evaluation,
            "sections": [
                {
                    "id": s.section_id,
                    "title": s.title,
                    "char_count": s.char_count,
                    "is_thin": s.is_thin(),
                    "source_agent": s.source_agent,
                }
                for s in self.sections
            ],
        }


# ── 对外接口（保持不变）──────────────────────────────────────────────

class ReportGenerator:
    @staticmethod
    def generate(data: dict) -> str:
        """
        主入口：data → IRDocument → validate → to_markdown
        外部调用方式与之前完全相同。
        """
        doc = IRDocument.from_agent_outputs(data)
        warnings = doc.validate()
        if warnings:
            _logger.warning("[Report] 章节质量警告: %s", warnings)
        return doc.to_markdown()

    @staticmethod
    def to_html(markdown_text: str) -> str:
        """Markdown → HTML 转换（用于下载）"""
        try:
            import markdown
            return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8">
<title>竞品分析报告</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; }}
  th {{ background: #f5f5f5; }}
  blockquote {{ color: #666; border-left: 4px solid #ddd; padding-left: 16px; margin: 0; }}
  code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }}
</style>
</head><body>
{markdown.markdown(markdown_text, extensions=['tables', 'fenced_code'])}
</body></html>"""
        except ImportError:
            return f"<pre>{markdown_text}</pre>"
