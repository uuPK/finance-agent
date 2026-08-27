# 可复现官方脱敏数据包

本目录提交了项目使用的赛事官方脱敏数据包（8 个 CSV、表描述和 Q&A 工作簿），用于在新环境重建与本仓库相同的 PostgreSQL 业务表和评测基线。数据发布已由项目维护方确认授权；目录中不包含 .env、API 密钥、数据库卷、审计日志、模型调用记录或评测运行记录。

使用项目根目录的 PowerShell 命令初始化：

    .\scripts\bootstrap_official_data.ps1

导入器将客户姓名字段标记为敏感字段，应用的 SQL 围栏禁止查询该字段。MANIFEST.sha256 记录每个源文件的字节数和 SHA-256；在加载前可据此核验数据完整性。

如需使用另一个已获授权的同版本脱敏数据副本，可传入数据目录：

    .\scripts\bootstrap_official_data.ps1 -DataDir "D:\contest-data\htsc"
