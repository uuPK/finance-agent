from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class TableMapping(BaseModel):
    source_file: str = Field(min_length=1)
    target_table: str = Field(pattern=r"^mart\.[a-z_]+$")
    # Keys are canonical mart columns; values are external CSV column names.
    columns: dict[str, str] = Field(min_length=1)
    required_source_columns: list[str] = Field(default_factory=list)

    @field_validator("source_file")
    @classmethod
    def require_csv(cls, value: str) -> str:
        if not value.lower().endswith(".csv"):
            raise ValueError("Only CSV source files are supported by the initial dataset adapter.")
        return value


class DatasetManifest(BaseModel):
    dataset_version: str = Field(min_length=1, max_length=64)
    source_type: str = Field(default="competition", min_length=1, max_length=32)
    anchor_date: str | None = None
    tables: list[TableMapping] = Field(min_length=1)


class MappingValidationResult(BaseModel):
    dataset_version: str
    valid: bool
    checked_files: int
    errors: list[str] = Field(default_factory=list)


class DatasetAdapter:
    """Validate a versioned CSV mapping before a competition dataset is loaded."""

    def validate(self, manifest: DatasetManifest, base_dir: Path) -> MappingValidationResult:
        errors: list[str] = []
        checked_files = 0
        target_tables: set[str] = set()
        for mapping in manifest.tables:
            if mapping.target_table in target_tables:
                errors.append(f"Duplicate target table mapping: {mapping.target_table}")
                continue
            target_tables.add(mapping.target_table)
            source_path = base_dir / mapping.source_file
            if not source_path.is_file():
                errors.append(f"Missing source file: {mapping.source_file}")
                continue
            checked_files += 1
            with source_path.open("r", encoding="utf-8-sig", newline="") as file:
                headers = set(csv.DictReader(file).fieldnames or [])
            required = set(mapping.required_source_columns) | set(mapping.columns.values())
            missing = sorted(required - headers)
            if missing:
                errors.append(f"{mapping.source_file}: missing columns {', '.join(missing)}")
        return MappingValidationResult(
            dataset_version=manifest.dataset_version,
            valid=not errors,
            checked_files=checked_files,
            errors=errors,
        )
