"""Load trusted skill packages and validate workflow dependencies before execution."""

from typing import Literal

from pydantic import BaseModel, Field


class Skill(BaseModel):
    id: str
    version: str
    description: str
    kind: Literal["code", "llm", "followup", "report"]
    depends_on: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    handler: str = ""
    input: str = "events-and-artifacts"
    output: str = "artifact"
    prompt: str = ""
    digest: str = ""
