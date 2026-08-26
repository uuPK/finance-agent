# 数据库与官方数据导入

`schema.sql` 创建官方 `mart` 业务表、可治理的 `metadata` 表、Agent 审计表和评测表；它不包含任何业务数据。官方 CSV 与 `Q&A.xlsx` 必须由部署者在本地提供，不能提交到仓库。

## 新库初始化

从项目根目录启动 PostgreSQL 并执行 schema：

```powershell
docker compose up -d postgres
Get-Content -Raw .\backend\db\schema.sql |
  docker exec -i finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1
```

随后从 `backend` 目录导入官方包并生成基线：

```powershell
uv sync --extra dev --frozen
uv run python .\db\load_official_dataset.py --data-dir "D:\contest-data\htsc"
uv run python .\db\load_official_benchmark_cases.py
```

数据包必须包含 `表描述.sql`、`Q&A.xlsx` 和 8 个官方 CSV。导入后有 8 张官方 `mart` 表、7 条官方原始问答、60 条官方基础回归题和 30 条独立扩展题。扩展题不写入检索样例，可独立运行以衡量泛化表现。

## 迁移原则

- 新库只需执行 `schema.sql`，不要手工补跑已被 schema 覆盖的旧迁移。
- 已部署的官方数据版本可按版本说明执行增量元数据迁移，例如 `007`、`008`。
- `006_replace_synthetic_with_official_dataset.sql` 会重建 `mart` schema，只适用于明确要从废弃合成数据迁移的本地环境；执行前必须备份并确认影响。
- 业务表与列结构是赛事数据边界；语义元数据的人工维护必须通过应用 API 和校验规则完成。

完整 Windows 步骤、验收 SQL、升级和故障排查见项目根目录的 [部署步骤.md](../../部署步骤.md)。
