# Architecture

## 目标

构建面向客户营销场景的可信智能问数 Agent。系统以 PostgreSQL 为数据底座，以 FastAPI 提供服务，以 LangGraph 编排 Actor-Critic 查询流程。

## 核心链路

```text
User Question
  -> Intent Parser
  -> Metadata Retriever
  -> QueryPlan Actor
  -> Plan Critic
  -> SQL Actor
  -> SQL Guardrail
  -> SQL Executor
  -> Result Critic
  -> Final Answer
```

## 关键设计

1. QueryPlan 先于 SQL

   模型先生成结构化 QueryPlan，再编译或生成 SQL。这样可以更早发现遗漏时间范围、指标口径、筛选条件和粒度错误。

2. Guardrail 分层

   - SQL 安全：只读、白名单、超时、行数限制。
   - Schema 合法性：表、字段、join 关系、指标定义必须存在。
   - 业务语义：QueryPlan 是否覆盖用户意图。
   - 结果合理性：字段、行数、粒度和解释是否一致。

3. Actor-Critic 修复闭环

   Critic 只负责指出问题并给出结构化修复建议，Actor 根据建议重新生成 QueryPlan 或 SQL。

4. 自动评测中心

   通过问答对持续统计 SQL 可执行率、结果准确率、一次通过率、修复后通过率、平均耗时和失败原因。

## 初始服务边界

- `backend/app/agents`: LangGraph 工作流与节点。
- `backend/app/guardrails`: SQL 和语义校验。
- `backend/app/metadata`: 元数据模型与检索。
- `backend/app/evaluation`: 离线评测流程。
- `backend/app/db`: PostgreSQL 连接与会话。
- `frontend/src`: 问数工作台、过程展示、元数据、评测中心。
