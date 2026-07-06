# Database

This directory contains PostgreSQL schema scripts for the Finance Agent project.

## Files

- `schema.sql`: Creates schemas, business-domain tables, metadata tables, agent runtime tables, and evaluation tables. It does not insert data.
- `seed_synthetic_data.py`: Inserts deterministic synthetic customer-marketing data for local development and SQL execution tests.

## Apply Locally

With the project PostgreSQL container running:

```bash
docker exec -i finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1 < backend/db/schema.sql
```

The script is idempotent for table creation and is safe to re-run during early development.

## Seed Synthetic Data

The default seed creates 500 synthetic customers, 180 days of asset snapshots, trades,
cash-flow records, positions, metadata definitions, business terms, join paths, and
question examples.

From the `backend` directory:

```bash
python db/seed_synthetic_data.py --reset --customers 500 --days 180
```

With `uv`:

```bash
uv run python db/seed_synthetic_data.py --reset --customers 500 --days 180
```

`--reset` truncates synthetic `mart` and `metadata` data before inserting new rows. Use it
only for local development databases, not for future official competition datasets.
