param(
    [string]$ImageTag = "eclipsesyson/syson:v2026.9.0",
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "infra/syson/docker-compose.yml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found. Install/start Docker Desktop first."
}

docker info | Out-Null
$env:IMAGE_TAG = $ImageTag

docker compose -f $composeFile up -d

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8080/api/rest/projects" -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ready) {
    docker compose -f $composeFile logs --tail 100 app
    throw "SysON did not become ready within $TimeoutSeconds seconds."
}

Write-Host "SysON is ready: http://localhost:8080"
Write-Host "Run: python scripts/syson_phase0.py run-all"
