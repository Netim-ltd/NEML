# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# Build Docker Hub images for the cluster and separate heavy-worker hosts.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DockerHubNamespace,
    [string]$Tag = '1.0',
    [switch]$Push,
    [switch]$IncludeWorkers
)

$ErrorActionPreference = 'Stop'
if ($DockerHubNamespace -notmatch '^[a-z0-9][a-z0-9_-]*$') {
    throw 'DockerHubNamespace must be a Docker Hub user or organization name.'
}
if ($Tag -notmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]*$') {
    throw 'Tag contains unsupported characters.'
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is required.' }
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$images = @(
    @{ Name = 'neml-brain'; Dockerfile = 'docker/brain/Dockerfile' }
)
if ($IncludeWorkers) {
    $images += @(
        @{ Name = 'neml-embed'; Dockerfile = 'docker/embed/Dockerfile' },
        @{ Name = 'neml-blender-mcp'; Dockerfile = 'docker/blender/Dockerfile' },
        @{ Name = 'neml-kicad-mcp'; Dockerfile = 'docker/kicad/Dockerfile' }
    )
}
foreach ($item in $images) {
    $image = "docker.io/$DockerHubNamespace/$($item.Name):$Tag"
    $dockerfile = Join-Path $repo $item.Dockerfile
    & docker build -f $dockerfile -t $image $repo
    if ($LASTEXITCODE -ne 0) { throw "Build failed: $image" }
    if ($Push) {
        & docker push $image
        if ($LASTEXITCODE -ne 0) { throw "Push failed: $image" }
    }
    Write-Host $image
}
