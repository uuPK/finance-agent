from typing import Literal

from pydantic import BaseModel, Field


SQLDialect = Literal["postgres"]


class SQLDraft(BaseModel):
    sql: str = Field(..., min_length=1)
    dialect: SQLDialect = "postgres"
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
