# Finance Agent

面向客户营销场景的可信智能问数 Agent。项目目标是把业务人员的自然语言问题转化为可校验、可解释、可修复的 SQL 查询，并通过自动评测证明查询准确率和响应时间。

## 项目定位

本项目不是简单的 Text-to-SQL demo，而是一个围绕金融客户营销场景设计的 Agentic 问数系统：

- 通过业务语义层理解客户、资产、交易、持仓、产品等概念。
- 通过 QueryPlan 中间层约束模型输出。
- 通过 Actor-Critic 流程生成、评审和修复查询。
- 通过 Guardrail 控制 SQL 安全、Schema 合法性和业务口径一致性。
- 通过评测中心量化 SQL 可执行率、结果准确率、一次通过率和修复后通过率。

## 技术栈

后端：

- Python
- FastAPI
- LangGraph
- SQLAlchemy
- PostgreSQL
- sqlglot
- Pydantic

前端：

- React
- TypeScript
- Vite
- Tailwind CSS
- TanStack Query
- TanStack Table
- Recharts

## 目录结构

```text
finance-agent/
  backend/          FastAPI, LangGraph, Guardrail, evaluation
  frontend/         React + TypeScript web app
  docs/             架构、元数据、评测和协作说明
  data/             样例数据说明，不提交真实或敏感数据
  docker-compose.yml
  .env.example
```

## 快速启动

1. 复制环境变量：

```bash
cp .env.example .env
```

2. 启动 PostgreSQL：

```bash
docker compose up -d postgres
```

3. 初始化数据库结构和本地 synthetic 数据：

```bash
docker exec -i finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1 < backend/db/schema.sql
cd backend
uv run python db/seed_synthetic_data.py --reset --customers 500 --days 180
```

4. 启动后端：

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

Windows PowerShell 可使用：

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

如果本机 `uv` 缓存目录权限异常，可以临时指定缓存目录：

```powershell
$env:UV_CACHE_DIR = "$env:TEMP\finance-agent-uv-cache"
uv sync
uv run uvicorn app.main:app --reload
```

5. 启动前端：

```bash
cd frontend
npm install
npm run dev
```

## 当前阶段

当前仓库已经实现核心问数主循环的前两段：

- QueryPlan Actor-Critic 生成、审核和修复循环。
- SQL Actor-Critic 生成、Guardrail 审核和修复循环。
- DeepSeek OpenAI-compatible 接口接入。
- SQL 目前只生成和审核，不执行数据库查询。
- 元数据召回、真实表结构适配、SQL 执行、结果审核将在后续阶段接入。

后端启动后可访问：

- `GET http://127.0.0.1:8000/api/health`
- `GET http://127.0.0.1:8000/api/llm/status`
- `POST http://127.0.0.1:8000/api/chat/query`

## 安全说明

public 仓库不得提交：

- `.env`
- API key
- 真实客户数据
- 原始赛题私有材料
- 未确认可公开的脱敏数据
- 本地数据库文件

请使用 `data/sample/` 放置可公开的合成样例数据。

## LLM 配置

项目通过标准 LLM 接口调用 OpenAI-compatible 模型，默认 provider 为 DeepSeek。

本地 `.env` 示例：

```bash
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
LLM_TIMEOUT_SECONDS=30
DEEPSEEK_API_KEY=your_api_key_here
```

不要把真实 API key 提交到 GitHub。`.env` 已被 `.gitignore` 排除。
