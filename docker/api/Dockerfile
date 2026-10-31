# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src
COPY dotnet/ ./dotnet/
RUN dotnet restore dotnet/Neml.Api/Neml.Api.csproj
RUN dotnet publish dotnet/Neml.Api/Neml.Api.csproj --no-restore -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:9.0
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/publish ./
USER $APP_UID
ENV ASPNETCORE_URLS=http://0.0.0.0:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "Neml.Api.dll"]
