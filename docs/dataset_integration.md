# 官方数据接入

Finance Agent 不附带赛事原始数据，也不支持以演示合成数据替代官方数据。部署者应从赛事组织方获得官方数据包，在本地完成导入。

## 数据包约束

解压后的顶层目录必须包含 `表描述.sql`、`Q&A.xlsx`，以及下列 8 个 UTF-8 CSV：

| 目标表 | 文件匹配模式 |
| --- | --- |
| `mart.ads_cust_info_d` | `ads_cust_info_d_*.csv` |
| `mart.dim_branch` | `dim_branch_*.csv` |
| `mart.dim_product` | `dim_product_*.csv` |
| `mart.dim_public` | `dim_public_*.csv` |
| `mart.dwd_cust_hold_d` | `dwd_cust_hold_d_*.csv` |
| `mart.dwd_cust_tran_d` | `dwd_cust_tran_d_*.csv` |
| `mart.dws_cust_aset_d` | `dws_cust_aset_d_*.csv` |
| `mart.dws_cust_fin_d` | `dws_cust_fin_d_*.csv` |

导入器保留官方字段名，并在导入过程中校验文件存在性、必需表与编码。不要手工修改官方字段名、业务表结构或数据文件以适配系统。

## 导入与生成评测基线

先初始化数据库结构，再从 `backend` 目录执行：

```powershell
uv run python .\db\load_official_dataset.py --data-dir "D:\contest-data\htsc"
uv run python .\db\load_official_benchmark_cases.py
```

第一条命令写入官方业务表、元数据和 7 条官方原始问答；第二条命令在官方表上实跑生成 60 条派生回归题及预期结果。完成后应有 67 条激活案例。

## 数据安全边界

- 原始 CSV、`Q&A.xlsx`、私有材料和可识别个人信息不得进入版本库。
- `data/` 目录只保存说明文件；本地原始数据应置于仓库外或已忽略的私有目录。
- 查询仅访问 `mart` schema；官方客户姓名字段被标记为敏感，不能进入生成 SQL 或结果。
- 任何数据版本切换都应重新生成评测基线，并在评测中心留下对应运行记录。
