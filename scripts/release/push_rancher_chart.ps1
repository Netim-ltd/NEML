# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# Package the Rancher chart as an OCI artifact in Docker Hub.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$DockerHubNamespace,
    [switch]$Push
)

$ErrorActionPreference = 'Stop'
if ($DockerHubNamespace -notmatch '^[a-z0-9][a-z0-9_-]*$') {
    throw 'DockerHubNamespace must be a Docker Hub user or organization name.'
}
if (-not (Get-Command helm -ErrorAction SilentlyContinue)) { throw 'Helm 3 is required.' }
$chart = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\deploy\rancher')).Path
$packageDir = Join-Path $env:TEMP 'neml-rancher-chart'
New-Item -ItemType Directory -Path $packageDir -Force | Out-Null
$repository = "docker.io/$DockerHubNamespace/neml-brain"
& helm lint $chart --skip-schema-validation --set "image.repository=$repository"
if ($LASTEXITCODE -ne 0) { throw 'Helm lint failed.' }
& helm package $chart --destination $packageDir
if ($LASTEXITCODE -ne 0) { throw 'Helm package failed.' }
$package = Join-Path $packageDir 'neml-brain-0.1.0.tgz'
if (-not (Test-Path -LiteralPath $package)) { throw 'Expected chart package was not created.' }
if ($Push) {
    # Login separately with `helm registry login registry-1.docker.io`.
    & helm push $package "oci://registry-1.docker.io/$DockerHubNamespace"
    if ($LASTEXITCODE -ne 0) { throw 'Docker Hub chart push failed.' }
}
Write-Host $package
