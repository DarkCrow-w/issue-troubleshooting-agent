"""Composition root: all concrete dependency choices live here."""

import yaml

from troubleshooter.config.settings import Settings
from troubleshooter.investigation.service import InvestigationService
from troubleshooter.logs.sources import SplunkSource
from troubleshooter.persistence.postgres import Store
from troubleshooter.skills import SkillRegistry


def build_service(settings: Settings) -> InvestigationService:
    config = yaml.safe_load(settings.config_path.read_text())
    environment_names = set(config.get("environments", {}))
    missing_connections = environment_names - set(settings.splunk_connections)
    if missing_connections:
        names = "、".join(sorted(missing_connections))
        raise ValueError(f"以下环境缺少 Splunk 连接配置：{names}")

    registry = SkillRegistry(settings.skills_dir, config)
    store = Store(settings.database_url)
    source = SplunkSource(settings, config)
    return InvestigationService(settings, config, registry, source, store)
