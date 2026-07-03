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

3. 启动后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Windows PowerShell 可使用：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

4. 启动前端：

```bash
cd frontend
npm install
npm run dev
```

## 当前阶段

当前仓库处于项目初始化阶段，重点包括：

- 协作目录和工程骨架
- PostgreSQL 开发环境
- FastAPI 基础服务
- LangGraph Actor-Critic 工作流占位
- 前端工作台基础结构
- 文档与 GitHub 协作模板

## 安全说明

public 仓库不得提交：

- `.env`
- API key
- 真实客户数据
- 原始赛题私有材料
- 未确认可公开的脱敏数据
- 本地数据库文件

请使用 `data/sample/` 放置可公开的合成样例数据。
