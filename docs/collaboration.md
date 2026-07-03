# Collaboration

## 分支模型

- `main`: 稳定分支。
- `dev`: 日常集成分支。
- `feature/*`: 功能分支。
- `fix/*`: 缺陷修复分支。

## Issue 标签

- `backend`
- `frontend`
- `agent`
- `guardrail`
- `metadata`
- `evaluation`
- `docs`
- `bug`
- `good first issue`

## PR 要求

- 描述改动动机和影响范围。
- 后端改动需要说明测试方式。
- 前端改动需要附截图或说明验证页面。
- 不提交 `.env`、真实数据、密钥或私有文档。

## 初始任务拆分

| 方向 | 任务 |
| --- | --- |
| 数据与元数据 | PostgreSQL 表结构、样例数据、指标口径、问答集 |
| Agent | LangGraph 工作流、Actor-Critic、QueryPlan prompt |
| 后端 | FastAPI API、SQL 执行器、Guardrail、日志 |
| 前端 | 问数工作台、过程展示、元数据页、评测页 |
| 评测 | 自动评测 runner、报告、失败原因分类 |
