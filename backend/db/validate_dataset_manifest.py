from __future__ import annotations

import argparse
from pathlib import Path

from app.data.dataset_adapter import DatasetAdapter, DatasetManifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a Finance Agent dataset mapping manifest."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    manifest = DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    result = DatasetAdapter().validate(manifest, manifest_path.parent)
    print(result.model_dump_json(indent=2))
    if not result.valid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
