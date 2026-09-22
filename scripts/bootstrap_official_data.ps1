[CmdletBinding()]
param(
    [string]$DataDir = (Join-Path $PSScriptRoot "..\data\official\htsc")
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedDataDir = (Resolve-Path $DataDir).Path

foreach ($file in @("表描述.sql", "Q&A.xlsx")) {
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedDataDir $file))) {
        throw "缺少官方数据文件：$file"
    }
}

Push-Location $projectRoot
try {
    docker compose up -d postgres
    Get-Content -Raw .\backend\db\schema.sql |
        docker exec -i finance-agent-postgres psql -U finance_agent -d finance_agent -v ON_ERROR_STOP=1

    Push-Location .\backend
    try {
        uv sync --extra dev --frozen
        uv run python .\db\load_official_dataset.py --data-dir $resolvedDataDir
        uv run python .\db\load_official_benchmark_cases.py
        uv run python .\db\load_official_challenge_v1_cases.py
        uv run python .\db\load_official_challenge_cases.py
        uv run python .\db\load_official_challenge_v3_cases.py
        uv run python .\db\load_official_challenge_v4_cases.py
        uv run python .\db\load_official_challenge_v5_cases.py
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}

docker exec finance-agent-postgres psql -U finance_agent -d finance_agent -c "select source_type, count(*) as active_cases from evaluation.eval_cases where is_active group by source_type order by source_type;"
