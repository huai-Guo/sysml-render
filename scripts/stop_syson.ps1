param(
    [switch]$DeleteData
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "infra/syson/docker-compose.yml"

if ($DeleteData) {
    docker compose -f $composeFile --profile render down -v
} else {
    docker compose -f $composeFile --profile render down
}
