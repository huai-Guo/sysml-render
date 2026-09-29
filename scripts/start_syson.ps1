param(
    [string]$ImageTag = "eclipsesyson/syson:v2026.9.0",
    [int]$TimeoutSeconds = 180,
    [switch]$Render
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "infra/syson/docker-compose.yml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI was not found. Install/start Docker Desktop first."
}

docker info | Out-Null
$env:IMAGE_TAG = $ImageTag

if ($Render) {
    docker compose -f $composeFile --profile render up -d --build
} else {
    docker compose -f $composeFile up -d
}

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

if ($Render) {
    $renderDeadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $renderReady = $false
    while ((Get-Date) -lt $renderDeadline) {
        try {
            $renderResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:3000/" -TimeoutSec 5
            if ($renderResponse.StatusCode -eq 200) {
                $renderReady = $true
                break
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    if (-not $renderReady) {
        docker compose -f $composeFile --profile render logs --tail 100 diagram-image-server
        throw "Diagram image server did not become ready within $TimeoutSeconds seconds."
    }
    Write-Host "Diagram image server is ready: http://localhost:3000"
}

Write-Host "Run: python scripts/syson_phase0.py run-all"
if ($Render) {
    Write-Host "Then: python scripts/syson_phase0.py export-images"
}
