import json
from pathlib import Path

from app.data.dataset_adapter import DatasetAdapter, DatasetManifest


def write_csv(path: Path, headers: str) -> None:
    path.write_text(f"{headers}\nC001,gold,active\n", encoding="utf-8")


def test_dataset_manifest_validates_a_mapped_csv(tmp_path: Path) -> None:
    write_csv(tmp_path / "customers.csv", "customer_no,customer_level,customer_status")
    manifest = DatasetManifest.model_validate(
        {
            "dataset_version": "competition-v1",
            "tables": [
                {
                    "source_file": "customers.csv",
                    "target_table": "mart.customer_info",
                    "columns": {"customer_no": "customer_no", "customer_level": "customer_level"},
                    "required_source_columns": ["customer_status"],
                }
            ],
        }
    )

    result = DatasetAdapter().validate(manifest, tmp_path)

    assert result.valid is True
    assert result.checked_files == 1
    assert result.errors == []


def test_dataset_manifest_reports_missing_columns_and_duplicate_targets(tmp_path: Path) -> None:
    write_csv(tmp_path / "customers.csv", "customer_no,customer_level,customer_status")
    (tmp_path / "assets.csv").write_text("customer_id,total_asset\n1,100\n", encoding="utf-8")
    manifest = DatasetManifest.model_validate_json(
        json.dumps(
            {
                "dataset_version": "competition-v1",
                "tables": [
                    {
                        "source_file": "customers.csv",
                        "target_table": "mart.customer_info",
                        "columns": {"customer_no": "customer_no"},
                    },
                    {
                        "source_file": "assets.csv",
                        "target_table": "mart.customer_info",
                        "columns": {"as_of_date": "as_of_date"},
                    },
                ],
            }
        )
    )

    result = DatasetAdapter().validate(manifest, tmp_path)

    assert result.valid is False
    assert "Duplicate target table mapping: mart.customer_info" in result.errors
