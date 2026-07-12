# Data Directory

此目录只存放可公开的合成样例数据说明。

不要提交真实客户数据、原始赛题私有材料或未确认可公开的脱敏数据。

`sample/competition_dataset_manifest.example.json` 是赛事数据的接入映射模板；在装载前使用
`backend/db/validate_dataset_manifest.py` 校验 CSV 文件、必填字段和目标表映射。
