"""
graph.py — LangGraph 分析图定义（P3.1）

将 5 阶段顺序编排迁移到 StateGraph DAG：

  research → analyst → product → strategist → evaluator
                                                    │
                    ┌── (score < 7 + 有补充查询) ────┘
                    ▼
               supplement → END
                    │
             (score >= 7) → END

优势：
  1. TypedDict 类型安全的状态传递
  2. MemorySaver 断点续跑（网络异常可恢复）
  3. draw_mermaid() 可视化流程图
"""
import asyncio
from typing import Optional

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from typing_extensions import TypedDict

from core.logger import get_logger

_logger = get_logger(__name__)


def _safe_usage(data: dict, node: str) -> int:
    """安全提取 usage token 数，非整数时记录警告并返回 0（P3-⑳）"""
    val = data.get("usage", 0)
    if isinstance(val, int):
        return val
    _logger.warning("[%s] usage 字段类型异常（%s），已忽略", node, type(val).__name__)
    return 0


# ── 状态定义 ──────────────────────────────────────────────────────────

class AnalysisState(TypedDict):
    """LangGraph 分析流程的完整状态（TypedDict 保证类型安全）"""
    # 输入
    competitor: str
    our_product: str
    prior_context: str
    # Agent 输出（初始 None，各节点逐步填入）
    research: Optional[dict]
    analysis: Optional[dict]
    product: Optional[dict]
    strategy: Optional[dict]
    evaluation: Optional[dict]
    # 统计
    total_tokens: int
    start_time: float


# ── 图构建函数 ────────────────────────────────────────────────────────

def build_analysis_graph(orchestrator):
    """
    构建并编译分析图。

    orchestrator 通过闭包传入，各节点可访问其 Agent 实例和 _progress_cb。
    返回 CompiledStateGraph，支持 ainvoke() 异步执行。
    """

    # ── 节点：researcher ──────────────────────────────────────────────

    async def research_node(state: AnalysisState) -> dict:
        data = await orchestrator.researcher.run(
            state["competitor"],
            orchestrator._progress_cb,
            prior_context=state.get("prior_context", ""),
        )
        return {
            "research": data,
            "total_tokens": state["total_tokens"] + _safe_usage(data, "research"),
        }

    # ── 节点：analyst ─────────────────────────────────────────────────

    async def analyst_node(state: AnalysisState) -> dict:
        data = await orchestrator.analyst.run(
            state["research"], orchestrator._progress_cb
        )
        return {
            "analysis": data,
            "total_tokens": state["total_tokens"] + _safe_usage(data, "analyst"),
        }

    # ── 节点：product ─────────────────────────────────────────────────

    async def product_node(state: AnalysisState) -> dict:
        data = await orchestrator.product.run(
            state["research"],
            state["analysis"],
            state["our_product"],
            orchestrator._progress_cb,
        )
        return {
            "product": data,
            "total_tokens": state["total_tokens"] + _safe_usage(data, "product"),
        }

    # ── 节点：strategist ──────────────────────────────────────────────

    async def strategist_node(state: AnalysisState) -> dict:
        data = await orchestrator.strategist.run(
            state["research"],
            state["analysis"],
            state["product"],
            state["our_product"],
            orchestrator._progress_cb,
        )
        return {
            "strategy": data,
            "total_tokens": state["total_tokens"] + _safe_usage(data, "strategist"),
        }

    # ── 节点：evaluator ───────────────────────────────────────────────

    async def evaluator_node(state: AnalysisState) -> dict:
        data = await orchestrator.evaluator.run(
            state["research"],
            state["analysis"],
            state["product"],
            state["strategy"],
            orchestrator._progress_cb,
        )
        return {
            "evaluation": data,
            "total_tokens": state["total_tokens"] + _safe_usage(data, "evaluator"),
        }

    # ── 节点：supplement（反思循环触发后执行）─────────────────────────

    async def supplement_node(state: AnalysisState) -> dict:
        """补充搜索 + 重跑 strategist（仅在 evaluator 判定不通过时执行）"""
        eval_result = state["evaluation"]
        gaps_str = "、".join(eval_result.get("gaps", [])) or "信息不足"

        if orchestrator._progress_cb:
            await orchestrator._progress_cb(
                f"⚠️ 质量评分 {eval_result['score']}/10（< 7 分），"
                f"缺口：{gaps_str}，补充搜索中..."
            )

        # 并发补充搜索
        queries = eval_result.get("supplement_queries", [])
        tasks = [
            orchestrator.researcher.searcher.async_search(q, max_results=3)
            for q in queries
        ]
        search_results = await asyncio.gather(*tasks, return_exceptions=True)

        supplement_parts = []
        for query, results in zip(queries, search_results):
            if isinstance(results, Exception):
                # gather(return_exceptions=True) 时搜索失败，跳过该条查询
                _logger.warning("[Supplement] 搜索失败，跳过 %r: %s", query, results)
                continue
            if isinstance(results, list) and results:
                formatted = orchestrator.researcher.searcher.format_results(results)
                supplement_parts.append(f"**补充查询：{query}**\n{formatted}")

        if not supplement_parts:
            # 搜索无实质结果，保持原状
            return {"research": state["research"], "strategy": state["strategy"]}

        supplement_text = "\n\n".join(supplement_parts)
        enhanced_research = dict(state["research"])
        enhanced_research["summary"] = (
            state["research"]["summary"]
            + f"\n\n---\n### 补充调研数据\n{supplement_text}"
        )

        if orchestrator._progress_cb:
            await orchestrator._progress_cb("🔄 基于补充数据重新生成 SWOT 与战略建议...")

        new_strategy = await orchestrator.strategist.run(
            enhanced_research,
            state["analysis"],
            state["product"],
            state["our_product"],
            orchestrator._progress_cb,
        )

        if orchestrator._progress_cb:
            await orchestrator._progress_cb(
                f"✅ 补充完成，报告已更新（评分 {eval_result['score']}/10 → 已补充）"
            )

        return {
            "research": enhanced_research,
            "strategy": new_strategy,
            "total_tokens": state["total_tokens"] + _safe_usage(new_strategy, "supplement"),
        }

    # ── 条件边：evaluator 后路由 ──────────────────────────────────────

    def route_after_eval(state: AnalysisState) -> str:
        """不通过且有补充查询 → supplement；否则 → END"""
        eval_result = state.get("evaluation") or {}
        if (
            not eval_result.get("passed", True)
            and eval_result.get("supplement_queries")
        ):
            return "supplement"
        return END

    # ── 组装图 ────────────────────────────────────────────────────────

    graph = StateGraph(AnalysisState)

    graph.add_node("research", research_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("product", product_node)
    graph.add_node("strategist", strategist_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("supplement", supplement_node)

    graph.set_entry_point("research")
    graph.add_edge("research", "analyst")
    graph.add_edge("analyst", "product")
    graph.add_edge("product", "strategist")
    graph.add_edge("strategist", "evaluator")
    graph.add_conditional_edges(
        "evaluator",
        route_after_eval,
        {"supplement": "supplement", END: END},
    )
    graph.add_edge("supplement", END)

    return graph.compile(checkpointer=MemorySaver())
