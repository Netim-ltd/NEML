# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# Read-only checks by default; -Deploy performs an explicit Helm installation.
[CmdletBinding()]
param(
    [string]$Context = 'neml-rancher',
    [Parameter(Mandatory = $true)][string]$Namespace,
    [Parameter(Mandatory = $true)][string]$ValuesFile,
    [string]$SecretName = 'neml-brain-secrets',
    [string]$ReleaseName = 'neml-brain',
    [switch]$Deploy
)

$ErrorActionPreference = 'Stop'
foreach ($command in @('kubectl', 'helm')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is required for Rancher cluster deployment."
    }
}
if ($Context -notmatch '^[a-zA-Z0-9._-]+$' -or $Namespace -notmatch '^[a-z0-9]([-a-z0-9]*[a-z0-9])?$') {
    throw 'Invalid kubeconfig context or Kubernetes namespace.'
}
$file = (Resolve-Path -LiteralPath $ValuesFile).Path
$chart = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\deploy\rancher')).Path
$contexts = @(& kubectl config get-contexts -o name)
if ($LASTEXITCODE -ne 0 -or $Context -notin $contexts) {
    throw "Kubeconfig context '$Context' is unavailable; import cluster credentials first."
}
$nodeJson = & kubectl --context $Context get nodes -o json
if ($LASTEXITCODE -ne 0) { throw 'Cluster access failed.' }
$nodes = (($nodeJson -join "`n") | ConvertFrom-Json).items
$ready = @($nodes | Where-Object {
    @($_.status.conditions | Where-Object { $_.type -eq 'Ready' -and $_.status -eq 'True' }).Count -gt 0
})
if ($ready.Count -eq 0) { throw 'The cluster has no Ready node.' }
foreach ($node in $ready) {
    Write-Host "$($node.metadata.name): $($node.status.allocatable.cpu) CPU, $($node.status.allocatable.memory) memory allocatable"
}
& helm lint $chart --values $file
if ($LASTEXITCODE -ne 0) { throw 'Helm chart lint failed.' }
& helm template $ReleaseName $chart --namespace $Namespace --values $file | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Helm chart rendering failed.' }
if ($Deploy) {
    & kubectl --context $Context get namespace $Namespace -o name | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Namespace '$Namespace' must be created first." }
    & kubectl --context $Context --namespace $Namespace get secret $SecretName -o name | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Secret '$SecretName' is missing." }
    & helm upgrade --install $ReleaseName $chart --kube-context $Context --namespace $Namespace --values $file --wait --timeout 10m
    if ($LASTEXITCODE -ne 0) { throw 'Helm deployment failed.' }
}
Write-Host 'Rancher cluster preflight passed.'
