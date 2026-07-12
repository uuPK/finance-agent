# Dataset Integration

Finance Agent uses a versioned CSV mapping manifest to validate an external dataset before it is loaded into the canonical `mart` model. The manifest declares the source file, destination table, canonical-target-to-source column mapping, required source fields, and dataset version. In each `columns` object, the key is the canonical `mart` field and the value is the field name in the source CSV.

Start from `data/sample/competition_dataset_manifest.example.json`, copy the source CSV files beside the manifest, and validate the package:

```powershell
cd backend
uv run python db/validate_dataset_manifest.py --manifest ../data/sample/competition_dataset_manifest.example.json
```

The validator checks that every declared file exists, all required columns are present, source file types are supported, and each canonical target table appears only once. This validation runs before any data load, so mapping defects are isolated before they affect the Agent, metadata catalog, or evaluation baseline.

After validation, complete the canonical field mapping for customer, asset, transaction, position, product, service relationship, cash-flow, and marketing tables. Register the dataset version in the evaluation run so accuracy can be compared across data releases.
