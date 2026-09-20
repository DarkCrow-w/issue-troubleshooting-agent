"""LangChain model adapter: prompts, JSON parsing, usage and bounded repair."""

import json
from logging import ERROR, WARNING
from time import monotonic
from typing import Protocol, TypeVar

from langchain.chat_models import init_chat_model
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel

from troubleshooter.config.settings import Settings
from troubleshooter.domain.errors import BudgetExceeded, ModelUnavailable
from troubleshooter.investigation.budget import RunBudget, estimate_tokens
from troubleshooter.observability.logging import log_event

from .prompts import DIAGNOSIS_PROMPT, SYSTEM_PROMPT
from .validation import validate_references

Result = TypeVar("Result", bound=BaseModel)


class JsonModel(Protocol):
    async def generate(
        self, prompt: str, payload: dict, schema: type[Result], valid_ids: set[str]
    ) -> Result: ...


class ModelClient:
    def __init__(self, settings: Settings, budget: RunBudget, model: BaseChatModel | None = None):
        self.settings = settings
        self.budget = budget
        self._model = model
        self._owns_model = model is None

    def _get_model(self) -> BaseChatModel:
        if self.settings.model_mode == "offline":
            raise ModelUnavailable("离线模式：未调用模型，仅输出规则提取的事实")
        if self._model is not None:
            return self._model
        if not self.settings.llm_api_key:
            raise ModelUnavailable("未配置模型密钥")
        # 客户端延迟创建；规则模式不需要模型连接，SDK 自动重试必须关闭以服从调用预算。
        self._model = init_chat_model(
            self.settings.llm_model,
            model_provider="openai",
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
            temperature=0.1,
            max_tokens=self.settings.llm_max_output_tokens,
            timeout=60,
            max_retries=0,
        )
        return self._model

    async def generate(
        self, prompt: str, payload: dict, schema: type[Result], valid_ids: set[str]
    ) -> Result:
        model = self._get_model()
        parser = PydanticOutputParser(pydantic_object=schema)
        messages = DIAGNOSIS_PROMPT.invoke(
            {
                "system": SYSTEM_PROMPT,
                "skill": prompt,
                "format_instructions": parser.get_format_instructions(),
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
            }
        ).to_messages()
        for attempt in range(2):
            response = await self._invoke(model, messages)
            try:
                result = parser.invoke(response)
                validate_references(result.model_dump(), valid_ids)
                return result
            except (OutputParserException, ValueError) as exc:
                log_event("model.output_rejected", level=WARNING, attempt=attempt + 1, error=exc)
                if attempt:
                    raise ModelUnavailable("模型输出或证据引用校验失败，已放弃该分析") from None
                messages.append(
                    HumanMessage(
                        content="上一次输出未通过格式或证据引用验证。请按给定 schema 重新输出，引用只能来自输入证据。"
                    )
                )
        raise ModelUnavailable("模型未返回有效结果")

    async def _invoke(self, model, messages):
        """一次调用只在这里计数；无论成功、修复还是失败，都不能绕过预算。"""
        serialized = json.dumps([m.model_dump() for m in messages], ensure_ascii=False)
        try:
            self.budget.reserve_model_call(estimate_tokens(serialized))
        except BudgetExceeded as exc:
            log_event("model.budget_exhausted", level=WARNING)
            raise ModelUnavailable(str(exc)) from None
        started = monotonic()
        log_event(
            "model.requested",
            model_calls=self.budget.usage.model_calls,
            estimated_input_tokens=estimate_tokens(serialized),
        )
        try:
            response = await model.ainvoke(messages, config={"run_name": "diagnose_json"})
        except Exception as exc:
            # 供应商异常可能带 URL、凭据或正文；仅记录错误类型与安全的代码位置。
            log_event(
                "model.request_failed",
                level=ERROR,
                error=exc,
                duration_ms=round((monotonic() - started) * 1000),
            )
            raise ModelUnavailable(f"模型接口不可用：{type(exc).__name__}") from None
        usage = response.usage_metadata or {}
        self.budget.record_model_usage(usage)
        log_event(
            "model.responded",
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            duration_ms=round((monotonic() - started) * 1000),
        )
        # 宽容 JSON 解析可能补齐结尾，但供应商标记截断的回答不能当作完整结论。
        if response.response_metadata.get("finish_reason") == "length":
            log_event("model.output_truncated", level=WARNING)
            raise ModelUnavailable("模型输出达到长度上限；当前分析未完成")
        return response

    async def aclose(self):
        if self._owns_model and self._model is not None:
            # 只关闭本类创建的 SDK 客户端；测试或调用方注入的模型由调用方管理。
            await self._model.root_async_client.close()
            self._model.root_client.close()
