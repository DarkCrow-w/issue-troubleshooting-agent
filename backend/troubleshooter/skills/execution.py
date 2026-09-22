"""Execute a trusted code strategy and turn failures into explicit partial results."""

from logging import WARNING

from troubleshooter.analysis import HANDLERS
from troubleshooter.investigation.state import InvestigationState
from troubleshooter.observability.logging import log_event

from .definition import Skill


def execute_code_skill(
    state: InvestigationState, skill: Skill, domain_config: dict
) -> dict:
    artifacts = dict(state["artifacts"])
    warnings = list(state["warnings"])
    try:
        if any(dependency not in artifacts for dependency in skill.depends_on):
            raise ValueError("缺少前序 skill 结果")
        result = HANDLERS[skill.handler](
            [
                event
                for event in state["events"].values()
                if event.scope == "transaction"
            ],
            domain_config,
            artifacts,
        )
        if not isinstance(result, dict):
            raise TypeError("代码 skill 必须返回字典")
        artifacts[skill.id] = result
    # Skill 是隔离边界；单个自定义实现失败不能中断其他确定性提取。
    except Exception as exc:  # noqa: BLE001
        log_event("skill.failed", level=WARNING, skill_id=skill.id, error=exc)
        artifacts.pop(skill.id, None)
        warnings.append(f"skill {skill.id} 执行失败：{type(exc).__name__}")
    return {"artifacts": artifacts, "warnings": warnings}


def extract_facts(
    state: InvestigationState, skills: list[Skill], config: dict
) -> InvestigationState:
    """Also used after interruption, when evidence exists but extraction has not finished."""
    result = dict(state)
    for skill in skills:
        if skill.kind == "code":
            result.update(execute_code_skill(result, skill, config))
    return result
