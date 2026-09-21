"""Application entry point: create a run, execute its graph and persist its outcome."""

import asyncio
import hashlib
import json
from collections.abc import Callable
from logging import DEBUG, ERROR, WARNING
from time import monotonic

from langsmith import tracing_context

from troubleshooter.config.settings import Settings
from troubleshooter.domain.models import InvestigationRequest
from troubleshooter.logs.sources import LogSource
from troubleshooter.models import ModelCallInterface, create_model_calls
from troubleshooter.observability.logging import log_event, task_context
from troubleshooter.persistence.postgres import Store
from troubleshooter.reports.builder import build_report
from troubleshooter.skills import SkillRegistry
from troubleshooter.skills.execution import extract_facts

from .budget import RunBudget
from .evidence import EvidenceCollector
from .followups import FollowupPlanner
from .graph import build_graph
from .model_steps import ModelSteps
from .state import initial_state

ModelFactory = Callable[[Settings, RunBudget], ModelCallInterface]


class InvestigationService:
    def __init__(
        self,
        settings: Settings,
        config: dict,
        registry: SkillRegistry,
        source: LogSource,
        store: Store,
        model_factory: ModelFactory = create_model_calls,
    ):
        self.settings, self.config, self.registry = settings, config, registry
        self.source, self.store, self.model_factory = source, store, model_factory

    async def run(self, task: dict, request: InvestigationRequest, progress: Callable):
        """建立任务日志上下文；业务流程和收尾由下方方法负责。"""
        started = monotonic()
        with task_context(task["id"]):
            log_event(
                "task.started",
                source_mode="splunk",
                model_mode="live",
            )
            try:
                await self._run(task, request, progress)
            except Exception as exc:
                log_event("task.unhandled_error", level=ERROR, error=exc)
                raise
            finally:
                log_event(
                    "task.finished",
                    status=task["status"],
                    duration_ms=round((monotonic() - started) * 1000),
                    warning_count=len((task.get("report") or {}).get("warnings", [])),
                )

    async def _run(self, task: dict, request: InvestigationRequest, progress: Callable):
        """依次组装依赖、运行状态图、恢复部分结果、保存最终报告。"""
        skills = self.registry.workflow(request.workflow)
        budget = RunBudget(self.settings)
        model = self.model_factory(self.settings, budget)
        collector = EvidenceCollector(self.source, self.store, self.config, budget, task["id"])
        planner = FollowupPlanner(
            request, next((s for s in skills if s.kind == "followup"), None), model, budget
        )
        models = ModelSteps(request, skills, model)
        state = initial_state(request)
        task["snapshot"] = self.snapshot(skills)
        task["steps"] = []

        def phase(message):
            task.update(phase=message, usage=budget.usage.model_dump())
            progress(task)

        graph = build_graph(request, self.config, skills, budget, collector, planner, models, phase)
        # 业务预算控制实际查询次数；图递归上限额外防止错误连边造成死循环。
        followup_rounds = self.settings.max_followups if request.followup_enabled else 0
        recursion_limit = (
            30
            + (len(skills) + 3) * (followup_rounds + 1)
            + 4 * self.settings.max_model_calls
        )
        try:
            # 禁止环境变量意外开启 LangSmith，避免公司日志发送到外部追踪服务。
            with tracing_context(enabled=False):
                async with asyncio.timeout(self.settings.task_timeout_seconds):
                    async for channel, data in graph.astream(
                        state,
                        stream_mode=["values", "updates"],
                        config={"recursion_limit": recursion_limit},
                    ):
                        if channel == "values":
                            state = data
                        else:
                            task["steps"].extend(data.keys())
                            for node in data:
                                log_event("graph.node_completed", level=DEBUG, stage=node)
            task["status"] = "partial" if state["warnings"] else "completed"
        except TimeoutError:
            log_event("task.timeout", level=WARNING)
            state["warnings"] = state["warnings"] + ["任务达到时间上限；报告仅包含已获取的证据"]
            task["status"] = "partial"
        except asyncio.CancelledError:
            log_event("task.cancelled")
            state["warnings"] = state["warnings"] + ["任务已取消，后续查询和模型调用已停止"]
            task["status"] = "cancelled"
        except Exception as exc:
            log_event("task.execution_failed", level=ERROR, error=exc)
            state["warnings"] = state["warnings"] + [
                f"排查执行失败：{type(exc).__name__}，请检查服务端配置"
            ]
            task["status"] = "failed"
        finally:
            await self._close_model(model, task, state)
        state = self._restore_partial_result(state, skills, models)
        report = build_report(state)
        task.update(phase="排查结束", usage=budget.usage.model_dump(), report=report)
        self.store.save(task)

    async def _close_model(self, model, task, state):
        """清理失败不能覆盖已经完成的排查，也不能阻止报告入库。"""
        try:
            await model.close()
        except Exception as exc:
            log_event("model.cleanup_failed", level=WARNING, error=exc)
            state["warnings"] += ["模型连接清理失败，已保留排查结果"]
            if task["status"] == "completed":
                task["status"] = "partial"

    def _restore_partial_result(self, state, skills, models):
        """中断可能发生在节点之间：保留已有事实和已完成的模型分块。"""
        if state["report"]:
            return state
        state = extract_facts(state, skills, self.config)
        if not state["skill_results"] or state["skill_index"] >= len(models.skills):
            return state
        skill = models.skills[state["skill_index"]]
        if skill.kind == "report":
            state["diagnoses"] = state["skill_results"]
            return state
        state["artifacts"][skill.id] = [result.model_dump() for result in state["skill_results"]]
        return state

    def snapshot(self, skills) -> dict:
        return {
            "config_hash": hashlib.sha256(
                json.dumps(self.config, sort_keys=True).encode()
            ).hexdigest(),
            "config": self.config,
            "skills": [{"id": s.id, "version": s.version, "digest": s.digest} for s in skills],
            "model": self.settings.llm_model,
            "model_mode": "live",
            "source_mode": "splunk",
            "runtime": "langgraph",
        }
