# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# Prepare the existing Compose stack for a local Rancher Desktop/Moby runtime.
[CmdletBinding()]
param(
    [switch]$StartRuntime,
    [switch]$BuildImages,
    [switch]$StartServices
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$compose = Join-Path $repo 'docker\compose.yml'
$envFile = Join-Path $repo '.env'

function Require-Command([string]$name) {
    $item = Get-Command $name -ErrorAction SilentlyContinue
    if (-not $item) { throw "$name is required. Install Rancher Desktop and its CLI first." }
    return $item
}

Require-Command 'rdctl' | Out-Null
Require-Command 'docker' | Out-Null
if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Create $envFile from .env.example and set unique secrets before starting services."
}
$envText = Get-Content -LiteralPath $envFile -Raw
if ($envText -notmatch '(?m)^POSTGRES_PASSWORD=(?!CHANGEME|\s*$).+') {
    throw 'POSTGRES_PASSWORD is missing or still a placeholder in .env.'
}
if ($envText -notmatch '(?m)^NEML_API_KEY=(?!CHANGEME|\s*$).+') {
    throw 'NEML_API_KEY is missing or still a placeholder in .env.'
}
if ($StartRuntime) {
    & rdctl start --application.start-in-background --container-engine.name=moby
    if ($LASTEXITCODE -ne 0) { throw 'Rancher Desktop could not start with Moby.' }
}
& docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Moby is not ready. Start Rancher Desktop and retry.' }

# The existing stack includes a GPU-only vLLM service and lab tool daemons.
# A valid Compose plan is checked before any build or container is started.
& docker compose --env-file $envFile -f $compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration is invalid.' }
if ($BuildImages) {
    & docker compose --env-file $envFile -f $compose build
    if ($LASTEXITCODE -ne 0) { throw 'One or more NEML images failed to build.' }
}
if ($StartServices) {
    & docker compose --env-file $envFile -f $compose up -d --wait postgres
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL did not become healthy.' }
    & docker compose --env-file $envFile -f $compose run --rm --no-deps brain alembic -c brain/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed; application services were not started.' }
    & docker compose --env-file $envFile -f $compose up -d
    if ($LASTEXITCODE -ne 0) { throw 'One or more NEML services failed to start.' }
}
Write-Host 'Rancher Desktop Moby and NEML Compose are ready.'
Write-Host 'Model TLS remains opt-in: configure certificates and run Compose with --profile edge.'
