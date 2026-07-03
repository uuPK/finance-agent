# Database

This directory contains PostgreSQL schema scripts for the Finance Agent project.

## Files

- `schema.sql`: Creates schemas, business-domain tables, metadata tables, agent runtime tables, and evaluation tables. It does not insert data.

## Apply Locally

With the project PostgreSQL container running:

```bash
docker exec -i finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1 < backend/db/schema.sql
```

The script is idempotent for table creation and is safe to re-run during early development.
