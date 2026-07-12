# Finance Agent

Finance Agent 是面向证券客户营销场景的可信智能问数系统。它将自然语言业务问题转换为受控的 QueryPlan 与只读 SQL，在生成、审核、执行、解释和评测各环节提供可追溯证据，并把自动评测与人工复核纳入同一条闭环。

系统服务于客户分层、资产与交易洞察、持仓分析、资金流监测、服务经理经营分析、产品偏好和营销活动效果分析等高频工作。业务人员从工作台提交问题后，实时看到系统所处阶段、已检索到的元数据、审核依据、SQL、执行结果和修复记录；系统不会向浏览器暴露模型隐藏推理、原始提示词、连接串或密钥。

## 核心能力

- 实时智能问数：基于 SSE 推送查询阶段、产物、修复尝试与终态，刷新或短暂断线后可按事件 ID 回放。
- 结构化 QueryPlan：将意图、指标、维度、筛选、时间范围、粒度、输出格式和安全约束固化为可审核中间层。
- 业务元数据检索：按问题检索表、字段、指标定义、业务术语、关联路径和高质量问答示例，为生成提供受控上下文。
- SQL 安全执行：仅允许单条只读 `SELECT`，限制表、字段、敏感字段、返回行数和执行时长，并在只读事务中运行。
- 结果工作台：最终结果以可横向滚动、固定表头的数据表呈现，过程中的元数据、QueryPlan、SQL、审核证据和错误均可展开查看。
- 澄清续跑：对高净值、活跃客户等存在多种业务口径的问题，系统先提出结构化澄清；补充信息后使用同一查询记录继续推理，历史过程完整保留。
- 评测与人工复核：以标准业务口径和可复算结果进行自动评分，高风险案例进入人工队列，人工修正可沉淀为回归基准和检索示例。

## 可信审核架构

查询结果在页面中保持最多 100 行预览；完成后的查询可按原审核 SQL 导出完整结果，支持 Excel、CSV 和 JSON。导出使用独立的只读执行上限与超时，并记录导出格式、行数、截断状态和耗时。

系统采用“三层自动审核 + 人工复核”的分层架构。每一层都输出可展示的结论、证据和修复建议，避免将不透明的模型内部推理作为可信依据。

```text
自然语言问题
    |
QueryPlan Actor -> 第 1 层：结构与口径硬审核 -> 第 2 层：独立 Plan Critic
    |                                        |                 |
    |<------------- 失败反馈与定向修复 -------+-----------------+
    v
SQL Actor       -> 第 1 层：SQL 安全硬审核  -> 第 2 层：独立 SQL Critic
    |                                        |                 |
    |<------------- 失败反馈与定向修复 -------+-----------------+
    v
只读 SQL 执行    -> 第 3 层：结果硬验证      -> 独立 Result Critic
    |
结果表格、审计事件、自动评测、人工复核
```

### 第 1 层：确定性硬审核

对 QueryPlan 校验必填结构、歧义状态、指标定义、输出限制和安全约束；对 SQL 校验单语句、只读性、禁止 DDL/DML、表与字段白名单、敏感字段和行数限制。确定性规则负责拦截不应进入执行环境的请求。

### 第 2 层：独立语义审核

Plan Critic 和 SQL Critic 与生成角色职责分离，分别检查业务意图是否完整、指标口径是否一致、筛选和关联路径是否正确、查询粒度是否合理。审核失败时，系统将结构化反馈送回对应 Actor，保留每次修复尝试和前序证据。

### 第 3 层：执行结果审核

SQL 在只读事务中执行后，Result Hard Validator 校验执行状态、字段、行数、敏感字段和粒度；Result Critic 再核对结果与原始业务问题、QueryPlan 和执行证据是否一致。通过三层审核的结果才进入最终回答与表格输出。

### 人工复核闭环

自动评测将执行失败、结果不一致、低置信度、发生修复、复杂跨域查询和澄清路径异常等案例标记为待复核。复核人员在同一工作面比对标准业务口径与 Agent 实际产物，给出“正确、错误、应澄清、数据不足”等结构化结论，并记录错误分类、严重程度和修正事实。

对于包含修正 QueryPlan、只读 SQL 或标准结果的复核结论，系统会进行安全校验后更新回归基准，并写入元数据问答示例库。这样既保留原始评测和人工审计记录，也让后续检索与生成能够复用经过确认的业务知识。

## 可量化的评测体系

内置基准数据集 `synthetic-v1` 由可复现的业务数据和可执行标准 SQL 共同生成，所有完成型案例均保存标准列、标准结果集、行数和比较规则，避免仅依赖人工主观判断。

| 维度 | 当前规模与约束 |
| --- | --- |
| 基准案例 | 15 个确定性案例，5 个简单、6 个中等、4 个复杂 |
| 业务覆盖 | 客户、资产、交易、持仓、资金流、产品、服务经理、营销活动 8 个主题域 |
| 澄清能力 | 2 类必须澄清案例，覆盖资产门槛与活跃口径 |
| 标准答案 | 13 个完成型案例均有可执行标准 SQL 与标准结果；2 个案例以结构化澄清为标准结果 |
| 自动指标 | SQL 可执行率、结果准确率、一次通过率、修复后通过率、平均耗时、计划/SQL/结果评分 |
| 安全边界 | 单条只读 SQL、默认最大 1,000 行、API 预览 100 行、SQL 超时 30 秒 |
| 修复控制 | QueryPlan 与 SQL 分别最多 2 次定向修复，历史尝试不覆盖 |
| 实时可见性 | SSE 事件追加持久化；15 秒心跳；支持 `Last-Event-ID` 增量重放 |

评测以业务结果等价性为核心：标准结果与 Agent 结果按字段和值进行归一化比较，数值按容差处理，不以 SQL 文本完全一致作为正确性的唯一依据。

## 评测与复核工作流

1. 在“评测与人工复核中心”运行完整评测集或按难度运行冒烟评测。
2. 系统按真实 Agent 流程执行案例，持久化 QueryPlan、SQL、结果、评分、耗时、失败原因和风险标签。
3. 自动将失败、低置信度、修复过、复杂或结果不一致的案例路由为待人工复核。
4. 创建复核批次后，可导出 CSV 或 JSONL，供业务专家离线核验；页面也支持直接裁定。
5. 将人工结论以 JSON/JSONL 导入。导入过程校验任务身份、状态与数据结构，并保留不可变的复核决策记录。
6. 包含修正事实的结论升级为回归案例和问答示例，后续批次持续验证修复效果。

JSONL 导入项格式如下：

```json
{
  "review_item_id": "uuid",
  "reviewer_id": "reviewer-01",
  "verdict": "incorrect",
  "error_class": "wrong_metric",
  "severity": "major",
  "corrected_query_plan": {"intent": "metric_query"},
  "corrected_sql": "select ...",
  "corrected_result": {"columns": [], "rows": [], "row_count": 0},
  "reviewer_note": "采用已确认的指标口径",
  "confidence": 0.95
}
```

## 数据与版本治理

业务数据、元数据与评测案例采用分层设计：业务事实表位于 `mart`，语义定义位于 `metadata`，运行审计位于 `agent`，基准案例与人工决策位于 `evaluation`。每条评测案例和评测批次均保留数据集版本、来源类型与标准结果；新增数据可通过字段映射、质量校验和版本登记接入，而工作台和审核链路保持使用统一的业务视图与元数据接口。

合成基准数据使用固定随机种子与锚点日期生成，确保同一配置可重复得到相同的业务事实和标准答案。`backend/db/seed_synthetic_data.py` 同时生成业务数据、元数据和评测案例，是本地演示、回归调试和端到端验证的统一入口。

## 架构概览

```text
frontend (React + TypeScript)
  |-- 智能问数工作台 / 查询历史 / 元数据 / 评测与人工复核
  |
FastAPI
  |-- /api/chat/runs                SSE 实时问数
  |-- /api/evaluation/runs          异步评测批次
  |-- /api/evaluation/review-*      人工复核、导出和导入
  |
QueryService
  |-- QueryPlan Actor / Plan Critic
  |-- SQL Actor / SQL Guardrail / SQL Critic
  |-- SQL Executor / Result Validator / Result Critic
  |
PostgreSQL
  |-- mart / metadata / agent / evaluation
```

## 快速启动

### 1. 配置环境变量

复制 `.env.example` 为 `.env`，填写模型服务配置：

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=your_api_key_here
LLM_TIMEOUT_SECONDS=30
LLM_PROXY_URL=
```

### 2. 启动 PostgreSQL 并初始化数据

```powershell
docker compose up -d postgres

docker exec -i finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1 < backend/db/schema.sql

docker cp backend/db/migrations/002_query_events.sql finance-agent-postgres:/tmp/002_query_events.sql
docker exec finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1 -f /tmp/002_query_events.sql

docker cp backend/db/migrations/003_evaluation_review.sql finance-agent-postgres:/tmp/003_evaluation_review.sql
docker exec finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1 -f /tmp/003_evaluation_review.sql

docker cp backend/db/migrations/004_query_exports.sql finance-agent-postgres:/tmp/004_query_exports.sql
docker exec finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1 -f /tmp/004_query_exports.sql

cd backend
uv sync
uv run python db/seed_synthetic_data.py --reset --customers 500 --days 180
```

### 3. 启动后端与前端

后端：

```powershell
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

前端：

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

打开 `http://127.0.0.1:5173` 即可进入智能问数工作台。

## API 摘要

| 接口 | 用途 |
| --- | --- |
| `POST /api/chat/runs` | 创建实时查询并立即返回 `query_id` 与 SSE 地址 |
| `GET /api/chat/runs/{query_id}/events` | 订阅阶段事件，支持 `Last-Event-ID` |
| `GET /api/chat/runs/{query_id}` | 恢复查询快照与事件历史 |
| `POST /api/chat/runs/{query_id}/clarifications` | 提交澄清信息并续跑原查询 |
| `GET /api/chat/runs/{query_id}/export` | 将完整查询结果导出为 Excel、CSV 或 JSON |
| `POST /api/evaluation/runs` | 创建异步评测批次 |
| `GET /api/evaluation/dashboard` | 获取评测核心指标与人工复核统计 |
| `GET /api/evaluation/runs/{eval_run_id}` | 获取案例级评分与风险路由结果 |
| `POST /api/evaluation/review-batches` | 将待复核案例组装为人工复核批次 |
| `GET /api/evaluation/review-batches/{id}/export` | 导出 CSV 或 JSONL 复核包 |
| `POST /api/evaluation/review-imports` | 导入人工复核结论并沉淀反馈 |

保留兼容接口 `POST /api/chat/query`，可供已有同步调用方继续使用。

## 测试与质量检查

```powershell
cd backend
uv run --no-dev --with pytest python -m pytest
uv run --no-dev --with ruff ruff check app tests

cd ../frontend
npm run lint
npm run build
```

## 安全边界

- 不提交 `.env`、API Key、真实连接串或敏感业务数据。
- SSE 事件、评测记录和复核导出均经过脱敏处理，不包含密钥、原始提示词、隐藏推理或敏感客户字段。
- SQL 始终在只读事务中执行，并受语法、表字段、敏感数据、行数与超时约束。
- 人工复核结论保留来源、审核人、严重程度、置信度和校验摘要，支持审计与回归追踪。
