# Finance Agent：面向证券客户营销的可信智能问数系统

> 以自然语言完成客户营销数据查询，并把“能回答”落实为可审计、可约束、可评测、可持续迭代的 Agent 闭环。

本项目对应华泰证券赛题 **《Agentic 智能问数在客户营销场景的应用》**。系统基于赛事官方脱敏数据构建：业务人员输入客户画像、资产、交易、持仓或营销分群问题后，系统生成结构化查询计划和只读 SQL，经过多层校验后执行，并完整保留过程证据与人工复核入口。

## 为什么适合这道赛题

| 赛题技术卡点 | 系统实现 | 可核验结果 |
| --- | --- | --- |
| 企业私有知识结构化与意图理解 | 表、字段、指标、业务术语、关联关系、问法样例与规则约束组成可检索元数据目录；自然语言先转 `QueryPlan`，再生成 SQL | 元数据中心支持检索；物理业务表结构只读，语义元数据可治理 |
| 大模型幻觉抑制与可信输出 | QueryPlan 硬校验、SQL AST 白名单、敏感字段拦截、只读事务、超时与行数限制、结果合理性校验、Actor-Critic 修复 | 任意 SQL 必须是单条受限 `SELECT`，且只可访问官方 `mart` schema |
| 工程化量化评测 | 7 条官方原始问答 + 60 条基础回归题 + 30 条扩展题 + 四轮各 30 条独立挑战题，共 217 条；记录可执行率、结果准确率、一次通过率、修复后通过率、耗时与失败原因 | 评测中心可分开运行独立题集、生成复核队列、导出复核包并回写裁定 |
| 人工闭环与持续运营 | 人工复核可补充纠正 SQL、结果与业务口径；合格内容可沉淀为指标、术语、关联、样例或规则，并保留审计记录 | 复核写入与元数据变更在同一事务中处理，避免部分成功 |

赛题目标是分钟级响应和最终执行准确率超过 90%。本仓库提供实现、官方数据导入、可运行工作台与可重复评测基线；实际通过率应以当前模型、密钥额度和评测中心的真实运行记录为准，而非用标准 SQL 的可执行性代替。

## 技术亮点

### 1. QueryPlan 优先的 Agentic 问数链路

系统不让模型直接裸写 SQL，而是先把问题拆成意图、指标、维度、过滤条件、时间范围、粒度和澄清项，再进入 SQL 生成与审核。

```text
自然语言问题
  -> 元数据召回（legacy 或 Milvus Hybrid）
  -> QueryPlan 生成与硬校验
  -> Plan Critic / 修复
  -> SQL 生成
  -> SQL Guardrail / SQL Critic / 修复
  -> 只读执行与结果校验
  -> 可解释答案、审计事件与导出结果
```

- LLM 不可用或输出不合规时，使用确定性规则计划作为兜底。
- Critic 输出结构化问题和修复建议，Actor 只在有限次数内重试，避免无止境循环。
- 时间、指标和结果粒度属于 QueryPlan 的显式字段，可在 SQL 之前发现遗漏与歧义。

### 2. 面向金融数据的纵深安全围栏

SQL 通过 `sqlglot` AST 解析后才允许执行，防止提示词注入或模型幻觉直接触达数据库。

- 仅允许单条、显式字段的 `SELECT`；禁止 DDL/DML、`SELECT INTO`、行锁和递归 CTE。
- 仅允许官方 `mart` schema、元数据白名单中的表和字段、经批准的函数，以及有界 `LIMIT` / `OFFSET`。
- 敏感列不允许出现在生成 SQL 中；官方客户姓名字段从结果链路中拦截。
- PostgreSQL 使用只读事务、语句超时和最大返回行数；即使上层校验失效也不允许写数据。
- 人工复核提交的纠正 SQL 也必须经过同一套实时物理表、字段和敏感列校验，不能绕过安全策略。

### 3. 物理数据只读、语义元数据可运营

官方业务数据表是固定边界，系统不提供修改 `mart` 表或列结构的接口。可由人工运营的部分包括：

- 指标口径与负责人
- 业务术语、同义词与默认计划片段
- 表关联关系
- 高质量问法样例及其预期 SQL / 结果
- 规则约束

新增指标仅能引用真实存在的 `mart` 表；新增关联仅能引用真实存在的表和字段。删除操作为软停用，审计历史保留。

### 4. 可观测、可追溯的业务体验

React 工作台通过 SSE 展示“接收问题—检索元数据—构建计划—审核/修复—执行—结果校验”的实时阶段。后端持久化查询运行、事件、步骤、Guardrail、SQL 执行、结果校验与导出记录，支持：

- 查询历史与全过程回放
- Excel、CSV、JSON 导出及导出审计
- 失败案例的人工复核和原因分级
- 从评测失败回流到元数据与回归语料的闭环

## 官方数据与评测基线

项目不包含旧的业务数据生成器。已获维护方确认可公开的赛事官方脱敏数据包（8 个 CSV、`Q&A.xlsx`、表描述与哈希清单）已纳入 `data/official/htsc`，由本地导入器校验后写入 PostgreSQL；.env、API 密钥、数据库卷和运行审计记录不提交：

| 业务域 | 官方表 |
| --- | --- |
| 客户画像 | `mart.ads_cust_info_d` |
| 客户资产与资金流 | `mart.dws_cust_aset_d`、`mart.dws_cust_fin_d` |
| 客户持仓与交易 | `mart.dwd_cust_hold_d`、`mart.dwd_cust_tran_d` |
| 产品、机构、公共码表 | `mart.dim_product`、`mart.dim_branch`、`mart.dim_public` |

- 官方原始问答：7 条 `OFFICIAL-*` 案例。
- 官方派生回归题：60 条 `REG-001` 至 `REG-060`，标准答案全部从同一官方表实际执行得到，绝非合成答案。
- 独立扩展集：30 条 `EXT-001` 至 `EXT-030`，同样由官方表实跑生成结果，但不写入检索样例，用于观察未见问法的泛化能力。
- 第一轮独立挑战集：30 条 `CHL-001` 至 `CHL-030`，由官方表实跑生成结果，不写入检索样例。
- 第二轮独立挑战集：30 条 `NEW-001` 至 `NEW-030`，覆盖新的阈值、维度、指标与多事实表交集，同样不写入检索样例。
- 第三轮独立挑战集：30 条 `V3-001` 至 `V3-030`，覆盖客户、资产、交易、持仓、资金流、产品、营业部和币种口径，同样不写入检索样例。
- 第四轮独立挑战集：30 条 `V4-001` 至 `V4-030`，覆盖 2 月末快照、Q1 区间与客户、资产、交易、持仓、资金流、产品和机构维度，同样不写入检索样例。
- 全部合计：217 条激活案例；扩展集和四轮独立挑战集均不参与检索，避免测试泄漏。
- 资产总额口径为 `nm_tot_aset + fc_pur_aset`；交易金额口径为 `buy_amt + sell_amt`。

详细的数据保密边界见 [data/README.md](data/README.md)，数据导入和验收命令见 [部署步骤.md](部署步骤.md)。

## 系统界面

- **智能问数**：自然语言提问、阶段流、查询计划、SQL、校验项与结果预览。
- **查询历史**：查看、恢复和导出历史查询；可提交业务异议进入复核队列。
- **元数据中心**：浏览官方表结构，并对语义元数据进行新增、编辑和软停用。
- **评测中心**：运行全部 217 题，或单独运行任一 30 题独立集，观察质量指标并创建/导出/回写人工复核批次。

## 快速开始

推荐在 Windows 10/11 上使用 Docker Desktop、uv 和 Node.js 22。完整的官方数据初始化、密钥配置、服务启动、验收、升级和故障排查请遵循：

> [Windows 部署与验收指南](部署步骤.md)

官方脱敏数据包已随仓库提供。核心初始化流程如下：

```powershell
git clone https://github.com/uuPK/finance-agent.git
cd finance-agent
Copy-Item .env.example .env

docker compose up -d postgres
Get-Content -Raw .\backend\db\schema.sql |
  docker exec -i finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1

.\scripts\bootstrap_official_data.ps1
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

在另一个终端启动前端：

```powershell
# 先进入项目根目录 finance-agent
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开 `http://127.0.0.1:5173`。

### Milvus Hybrid 元数据检索（Phase 2）

`RETRIEVER_MODE=hybrid` 时，后端将 PostgreSQL 中启用的表、字段、指标、术语、关联、样例和规则统一投影为 `MetadataDocument`，增量同步到同一个 Milvus collection。Milvus 内置 BM25 稀疏索引与智谱 `embedding-3` Dense 索引分别召回；QueryAnalysis 和软 Metadata Filter 缩小候选，RRF 融合后调用智谱 `rerank` 对 TopN 重排。检索证据记录两路名次、融合分数、重排分数和入选原因。旧 Retriever 保留，Hybrid 不可用时会回退并记录原因。

```powershell
docker compose up -d postgres milvus
# 在本地 .env 填写 ZHIPU_RETRIEVAL_API_KEY，并设 RETRIEVER_MODE=hybrid
cd backend
uv sync --extra dev --frozen
```

首次 Hybrid 查询会为元数据生成向量并写入 Milvus；后续只更新内容变化的文档。此过程会把元数据文本（包括 schema、指标定义和样例 SQL）发送给智谱，请仅在已授权该数据流向时启用。新部署默认仍是 `legacy`，可以用 `.env` 中的 `ENABLE_RERANKER=false` 做重排消融。修改 `.env` 后重启后端。

### 预算化 Context Engine（Phase 3）

`SchemaContextProvider` 保留完整的数据库元数据和 SQL Guardrail 白名单，但给模型的 `prompt_context` 是独立的工作集。它按指标定义、必需字段、JOIN、业务术语等优先级选择内容，先压缩非关键描述，再淘汰低优先级项；必需证据装不下时失败关闭，不悄悄删掉。`SCHEMA_CONTEXT_BUDGET` 默认 10000，是模型无关的 JSON token **估算值**，不是模型 API 返回的精确 token 用量。`context_stats` 记录预算、已用估算 token、条目数、去重、压缩、淘汰与检索次数。

`SchemaContextProvider.expand(current, MissingContextRequest, question=..., query_plan=...)` 提供按类型定向补充接口：Hybrid 模式在 Milvus 内仅召回请求的文档类型，Legacy 模式使用同类 PostgreSQL 元数据兜底；补充结果重新合并、去重和预算裁剪。`STAGE_RETRIEVAL_BUDGET` 与 `GLOBAL_RETRIEVAL_BUDGET` 限制额外调用。当前阶段**尚未**让 Actor 自动发起扩展或让 Harness 路由失败；那属于后续 QueryPlan/Harness 阶段，现有 API/SSE 行为保持兼容。

## 本地质量检查与持续集成

```powershell
cd backend
uv run ruff check app tests
uv run pytest

cd ..\frontend
npm run lint
npm run build
```

GitHub Actions 会在 `main` 推送和 Pull Request 时自动执行上述后端静态检查/测试与前端 lint/build，工作流见 [.github/workflows/ci.yml](.github/workflows/ci.yml)。模型调用型 217 题全量回归会消耗 API 额度；可先单独运行 30 题独立集，再按版本运行全量评测，并将真实结果作为发布依据。

## 项目结构

```text
backend/
  app/                 FastAPI、Agent、Guardrail、元数据、评测与审计服务
  db/                  官方数据导入器、217 题回归生成器、schema 与迁移文件
  tests/               数据契约、LLM 解析、导出、元数据与 SQL 安全回归测试
frontend/
  src/                 智能问数、历史、元数据和评测中心界面
data/                  已获授权公开的官方脱敏数据、哈希清单与接入说明
docs/                  架构、评测、数据集与演示材料
```

## 相关文档

- [架构说明](docs/architecture.md)
- [评测设计](docs/evaluation_design.md)
- [官方数据与评测基线](docs/official_dataset.md)
- [演示脚本](docs/demo_script.md)
- [数据库说明](backend/db/README.md)

## 运行边界

本项目当前面向本地演示和赛事交付。若接入多人或生产环境，需在现有数据安全围栏之外补充统一身份认证、角色权限、密钥托管、审计留存策略、限流和数据库备份恢复机制。
