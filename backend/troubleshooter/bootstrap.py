"""Composition root: all concrete dependency choices live here."""

import yaml

from troubleshooter.config.settings import Settings
from troubleshooter.investigation.service import InvestigationService
from troubleshooter.logs.sources import ReplaySource, SplunkSource
from troubleshooter.persistence.postgres import Store
from troubleshooter.skills import SkillRegistry


def build_service(settings: Settings) -> InvestigationService:
    if settings.source_mode not in ("replay", "live") or settings.model_mode not in (
        "offline",
        "live",
    ):
        raise ValueError("SOURCE_MODE 必须是 replay/live，MODEL_MODE 必须是 offline/live")
    if settings.source_mode == "live" and settings.service_token == "local-development-only":
        raise ValueError("live 模式必须更换 SERVICE_TOKEN")
    config = yaml.safe_load(settings.config_path.read_text())
    registry = SkillRegistry(settings.skills_dir, config)
    store = Store(settings.database_url)
    source = (
        ReplaySource(settings.replay_path, config)
        if settings.source_mode == "replay"
        else SplunkSource(settings, config)
    )
    return InvestigationService(settings, config, registry, source, store)
