# Evaluation Design

## 评测目标

评测中心用于证明 Agent 的可用性，并指导后续迭代。

## 评测维度

- SQL 可执行率
- 结果准确率
- 一次通过率
- 修复后通过率
- 平均响应时间
- 表选择准确率
- 字段选择准确率
- 指标口径准确率
- 失败原因分布

## Query Case 分层

| 复杂度 | 示例 |
| --- | --- |
| 简单 | 单表单指标、单条件 |
| 中等 | 多表单指标、多条件 |
| 复杂 | 多表多指标、跨主题域、客群筛选 |

## 失败原因分类

- `missing_filter`: 遗漏筛选条件。
- `missing_time_range`: 遗漏时间范围。
- `wrong_metric`: 指标口径错误。
- `wrong_table`: 表选择错误。
- `wrong_join`: join 路径错误。
- `invalid_sql`: SQL 不可执行。
- `unsafe_sql`: SQL 触发安全规则。
- `wrong_grain`: 查询粒度错误。
- `empty_result`: 结果为空且不符合预期。

## 初始交付

第一版评测中心先支持读取本地问答 case，逐条运行查询流程，并输出 JSON 报告。
