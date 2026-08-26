# 官方数据与评测基线

官方包包含 8 个 CSV 表和 `Q&A.xlsx`。导入器直接保留官方字段名，并写入下列版本标记：

- 数据版本：`official-v1`
- 元数据版本：`official-metadata-v1`
- 问答基线：官方工作簿的 7 个 SQL 案例，以及基于同一批官方表实跑生成的 60 个回归案例

资产总额使用 `nm_tot_aset + fc_pur_aset`；交易额使用 `buy_amt + sell_amt`。客户姓名仅用于导入后敏感字段标注，任何生成 SQL 均不得选取该字段。

## 60 题官方回归题库

运行下列命令会将 60 道题逐条在**已经加载的官方数据库**中执行，并将实际结果写入 `evaluation.eval_cases` 与 `metadata.question_examples`：

```powershell
cd backend
.venv\Scripts\python.exe db\load_official_benchmark_cases.py
```

题库覆盖客户画像（12）、资产（12）、交易（14）、持仓（10）、资金流及营销分群（12），难度分布为简单 23、中等 31、复杂 6。其 `source_type` 为 `official_derived`：这表示题目是从官方表推导出来的评测题，**不是**合成记录或虚构答案。

导入器会保留 7 条 `OFFICIAL-*` 原始官方问答，刷新 `REG-001` 至 `REG-060`，并停用已不在当前题库中的旧派生题。每道题均具有：问题文本、标准 SQL、实跑结果集、版本和标签；结果比较使用无序行比较。

要复核导入结果，可查询 8 张 `mart` 表的行数，并确认 `evaluation.eval_cases` 中有 7 条 `official` 和 60 条激活的 `official_derived` 案例。实际模型通过率应通过评测接口或评测运行记录统计，不能把“标准 SQL 可执行”误报为模型通过。
