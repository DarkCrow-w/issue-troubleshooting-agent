"""Composition root: all concrete dependency choices live here."""

import yaml

from troubleshooter.config.settings import Settings
from troubleshooter.investigation.service import InvestigationService
from troubleshooter.logs.sources import SplunkSource
from troubleshooter.persistence.postgres import Store
from troubleshooter.skills import SkillRegistry


def build_service(settings: Settings) -> InvestigationService:
    config = yaml.safe_load(settings.config_path.read_text())
    registry = SkillRegistry(settings.skills_dir, config)
    store = Store(settings.database_url)
    source = SplunkSource(settings, config)
    return InvestigationService(settings, config, registry, source, store)
