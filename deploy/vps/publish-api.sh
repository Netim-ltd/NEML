#!/bin/sh
# Build the API + Blazor app on a dev machine and ship it to the host (the host has no SDK and
# little disk). Usage: ./publish-api.sh user@host   (run from the repo root's deploy/vps)
set -eu
host="$1"
out="$(mktemp -d)"
dotnet publish ../../dotnet/Neml.Api/Neml.Api.csproj -c Release -r linux-arm64 --self-contained false -o "$out/api-publish"
tar -C "$out" -cf - api-publish | ssh "$host" 'mkdir -p ~/neml/deploy/vps && tar -C ~/neml/deploy/vps -xf -'
echo "shipped: now on the host, in deploy/vps: sudo docker compose build api && sudo docker compose up -d --no-build api"
