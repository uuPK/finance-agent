# 评测设计

## 目标

评测中心用于量化当前模型和元数据版本下的 Agent 可用性，并将失败案例导入人工复核与元数据迭代闭环。它评价的是 Agent 实际生成和执行的结果，不把标准 SQL 的可执行性当作模型通过率。

## 基线组成

| 来源 | 数量 | 说明 |
| --- | ---: | --- |
| `official` | 7 | 官方 `Q&A.xlsx` 原始问答 |
| `official_derived` | 60 | 仅使用官方表、由标准 SQL 实跑生成预期结果的回归题 |
| `official_extension` | 30 | 仅使用官方表、由标准 SQL 实跑生成预期结果的独立扩展题；不进入检索样例 |
| `official_challenge_v2` | 30 | 第二轮独立挑战题；不进入检索样例，覆盖新的阈值、维度、指标与多事实表交集 |
| `official_challenge_v3` | 30 | 第三轮独立挑战题；不进入检索样例，覆盖客户、资产、交易、持仓、资金流、产品、营业部和币种口径 |
| `official_challenge_v4` | 30 | 第四轮独立挑战题；不进入检索样例，覆盖 2 月末快照、Q1 区间与客户、资产、交易、持仓、资金流、产品和机构维度 |
| 合计 | 187 | 核心基线简单 23、中等 31、复杂 6；四组独立题集各 30 条 |

60 条派生题和第一组 30 条独立题可通过 `backend/db/load_official_benchmark_cases.py` 重复生成；第二至第四组 30 条独立题分别由 `backend/db/load_official_challenge_cases.py`、`backend/db/load_official_challenge_v3_cases.py`、`backend/db/load_official_challenge_v4_cases.py` 生成。题库覆盖客户画像、资产、交易、持仓、资金流和营销分群；它们不是模拟业务记录或虚构答案。四组独立题只写入评测表，不写入 `metadata.question_examples`，避免通过精确题目/SQL 样例造成测试泄漏。

## 评测流程

```text
加载激活案例
  -> 逐题运行当前 QueryService
  -> 记录 QueryPlan、SQL、结果、耗时与校验事件
  -> 比较状态、计划要素和无序结果集
  -> 自动分级并进入人工复核队列
  -> 人工裁定 / 修正 SQL / 补充元数据
  -> 重新运行回归评测验证改进
```

## 核心指标

- **可执行率**：生成 SQL 且执行完成的比例。
- **结果准确率**：状态与标准结果集均正确的比例。
- **一次通过率**：未经过修复即得到正确结果的比例。
- **修复后通过率**：经过有限修复后得到正确结果的比例。
- **平均耗时**：单题端到端运行耗时。
- **计划得分**：意图、指标、条件、维度和澄清字段与标准计划的匹配情况。
- **失败原因分布**：用于定位优先修复的模型、元数据或规则问题。

## 失败分类与路由

| 失败类型 | 说明 | 优先处理方向 |
| --- | --- | --- |
| `missing_filter` / `missing_time_range` | 缺少业务筛选或时间范围 | QueryPlan 提示与术语口径 |
| `wrong_metric` / `wrong_grain` | 指标口径或聚合粒度错误 | 指标元数据、样例和结果校验 |
| `wrong_table` / `wrong_join` | 表或关联路径错误 | 表、字段和关联元数据 |
| `invalid_sql` / `unsafe_sql` | SQL 不可执行或触发安全围栏 | SQL Actor、Guardrail 修复反馈 |
| `empty_result` / `result_mismatch` | 结果为空或与预期不一致 | 过滤条件、日期口径和标准结果 |
| `runtime_error` | 调用、数据库或服务运行异常 | 服务健康、密钥和运行环境 |

高风险或阻断失败自动进入人工复核。复核可将完整、受安全校验的纠正 SQL 与结果回写为新的回归事实；也可以新增受治理的业务术语、指标、关联、样例或规则。物理业务表不在复核修改范围内。

## 运行方式

在前端“评测中心”发起完整评测，或通过 `/api/evaluation/runs` 接口启动。评测可传入 `case_source: "official_extension"`、`"official_challenge_v2"`、`"official_challenge_v3"` 或 `"official_challenge_v4"` 单独运行一组 30 条独立题。每次运行会记录数据集、模型与提示词版本字段以及所有逐题结果。完整 187 题运行会调用模型服务并消耗额度，应以评测记录中的真实结果作为是否达到赛题准确率目标的证据。
