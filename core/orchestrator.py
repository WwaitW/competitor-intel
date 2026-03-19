"""
orchestrator.py — Agent 编排器（P3.1 LangGraph 架构）

内部使用 LangGraph StateGraph 驱动，外部接口与之前完全兼容：
  run(competitor, our_product, progress_callback) -> dict

DAG 拓扑：
  research → analyst → product → strategist → evaluator
                                                   │
               ┌── (score < 7 + 有补充查询) ────────┘
               ▼
          supplement → END

新增：
  - prior_context 参数：可传入历史分析摘要，支持增量分析
  - get_graph_diagram()：返回 Mermaid 格式的流程图字符串
"""
import asyncio
import time
from typing import Callable, Optional

from agents.researcher import ResearcherAgent
from agents.analyst import AnalystAgent
from agents.product import ProductAgent
from agents.strategist import StrategistAgent
from agents.evaluator import EvaluatorAgent
from core.graph import build_analysis_graph, AnalysisState


class Orchestrator:
    def __init__(self, model: str = None):
        self.model = model
        self.researcher = ResearcherAgent(model=model)
        self.analyst = AnalystAgent(model=model)
        self.product = ProductAgent(model=model)
        self.strategist = StrategistAgent(model=model)
        self.evaluator = EvaluatorAgent(model=model)

        # progress_callback 存储在实例上，图节点通过闭包访问
        self._progress_cb: Optional[Callable] = None

        # 编译 LangGraph 图（MemorySaver 支持断点续跑）
        self._graph = build_analysis_graph(self)

    async def run(
        self,
        competitor: str,
        our_product: str = "",
        progress_callback: Optional[Callable] = None,
        prior_context: str = "",
    ) -> dict:
        """
        完整分析流程，返回所有中间数据（含评估结果）。
        公共接口与重构前完全兼容。
        """
        self._progress_cb = progress_callback
        start_time = time.time()

        initial_state: AnalysisState = {
            "competitor": competitor,
            "our_product": our_product,
            "prior_context": prior_context,
            "research": None,
            "analysis": None,
            "product": None,
            "strategy": None,
            "evaluation": None,
            "total_tokens": 0,
            "start_time": start_time,
        }

        # 每次分析使用独立的 thread_id（MemorySaver 隔离）
        thread_id = f"{competitor}_{int(start_time * 1000)}"
        graph_config = {"configurable": {"thread_id": thread_id}}

        final_state = await self._graph.ainvoke(initial_state, config=graph_config)

        # evaluator 通过时在主流程补发进度消息（route_after_eval 中无法 await）
        eval_result = final_state.get("evaluation") or {}
        if eval_result.get("passed", True) and progress_callback:
            score = eval_result.get("score", "?")
            verdict = eval_result.get("verdict", "")
            await progress_callback(f"✅ 质量评分：{score}/10 — {verdict}")

        total_tokens = final_state.get("total_tokens", 0)
        elapsed = round(time.time() - start_time, 1)
        cost = round(total_tokens / 1_000_000 * 0.15, 4)

        return {
            "competitor": competitor,
            "our_product": our_product,
            "research": final_state["research"],
            "analysis": final_state["analysis"],
            "product": final_state["product"],
            "strategy": final_state["strategy"],
            "evaluation": final_state["evaluation"],
            "meta": {
                "elapsed_seconds": elapsed,
                "total_tokens": total_tokens,
                "estimated_cost_usd": cost,
            },
        }

    async def run_batch(
        self,
        competitors: list[str],
        our_product: str = "",
        progress_callback: Optional[Callable] = None,
        prior_contexts: Optional[dict[str, str]] = None,
    ) -> list[dict]:
        """
        并发分析多个竞品，返回 list[dict]，每个元素是单竞品完整 data。

        每个竞品使用独立的 Orchestrator 实例，互不干扰。
        prior_contexts: {competitor: prior_context_text}，可选。
        progress_callback: (msg: str) -> None，批量进度消息（含竞品名前缀）。
        """
        prior_contexts = prior_contexts or {}

        # 并发度控制：最多 2 个竞品同时调用 LLM，避免触发 OpenRouter 限流
        _sem = asyncio.Semaphore(2)

        async def run_one(competitor: str) -> dict:
            async with _sem:
                orch = Orchestrator(model=self.model)

            async def prefixed_cb(msg: str):
                if progress_callback:
                    await progress_callback(f"[{competitor}] {msg}")

            return await orch.run(
                competitor=competitor,
                our_product=our_product,
                progress_callback=prefixed_cb,
                prior_context=prior_contexts.get(competitor, ""),
            )

        results = await asyncio.gather(
            *[run_one(c) for c in competitors],
            return_exceptions=True,
        )

        # 将 exception 转为带 error 字段的 dict，不中断整批
        output = []
        for competitor, result in zip(competitors, results):
            if isinstance(result, Exception):
                output.append({
                    "competitor": competitor,
                    "error": str(result),
                    "research": None, "analysis": None,
                    "product": None, "strategy": None,
                    "evaluation": None,
                    "meta": {"elapsed_seconds": 0, "total_tokens": 0, "estimated_cost_usd": 0},
                })
            else:
                output.append(result)
        return output

    def get_graph_diagram(self) -> str:
        """返回 Mermaid 格式的流程图（可粘贴到 mermaid.live 预览）"""
        try:
            return self._graph.get_graph().draw_mermaid()
        except Exception:
            return "（图形渲染不可用，请确认 langgraph 版本 >= 0.2.0）"
