# Database

This directory contains PostgreSQL schema scripts for the Finance Agent project.

## Files

- `schema.sql`: Creates the official competition mart tables, metadata tables, agent runtime tables, and evaluation tables. It does not insert data.
- `load_official_dataset.py`: Validates and imports the official CSV and Q&A workbook, then rebuilds metadata and evaluation cases.

## Apply Locally

With the project PostgreSQL container running:

```bash
docker exec -i finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1 < backend/db/schema.sql
```

The script is idempotent for table creation and is safe to re-run during early development.

## Load the official package

From the `backend` directory, run the schema script and then import the extracted official
package directory. The importer loads all eight official tables and the seven provided Q&A
cases; it also rebuilds the metadata and evaluation baseline from that package.

```bash
python db/load_official_dataset.py --data-dir <official-package-directory>
```
