# Finance Agent

面向证券客户营销场景的智能问数项目。当前运行数据已切换为赛事官方脱敏数据包；项目不再包含用于演示的业务数据生成器或旧业务表。

## 官方数据模型

| 领域 | 表 |
| --- | --- |
| 客户 | `mart.ads_cust_info_d` |
| 资产与资金 | `mart.dws_cust_aset_d`、`mart.dws_cust_fin_d` |
| 持仓与交易 | `mart.dwd_cust_hold_d`、`mart.dwd_cust_tran_d` |
| 产品、机构与码表 | `mart.dim_product`、`mart.dim_branch`、`mart.dim_public` |

所有查询仅能访问 `mart` schema 的官方表。`ads_cust_info_d.name` 是敏感字段，不会返回给用户。

## 数据导入

先执行 `backend/db/schema.sql`，再对官方压缩包解压目录运行：

```bash
cd backend
python db/load_official_dataset.py --data-dir <官方数据包解压目录>
```

导入器会校验 8 个 CSV、写入数据库，并从官方 `Q&A.xlsx` 生成问答案例和评测基线。

## 问数约束

- 查询为单条只读 `SELECT`，必须包含 `LIMIT`。
- 表、列、函数与 schema 均由元数据白名单约束。
- 客户关联使用 `pty_id`，产品关联使用 `prdt_id`，机构关联使用 `org_id`。
- `data_dt` 是 `YYYYMMDD` 文本，时间范围必须明确。
