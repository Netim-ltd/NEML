# Copyright (c) 2026 Mustafa Gulsoy.
# SPDX-License-Identifier: AGPL-3.0-or-later
# Runtime image for a pre-published API (see publish-api.sh); no SDK is needed on the host.
FROM mcr.microsoft.com/dotnet/aspnet:9.0
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl     && rm -rf /var/lib/apt/lists/*
COPY api-publish/ ./
# Recordings pushed by the lab; a named volume mounted here inherits this owner.
RUN mkdir -p /data/media && chown $APP_UID /data/media
USER $APP_UID
ENV ASPNETCORE_URLS=http://0.0.0.0:8080
ENTRYPOINT ["dotnet", "Neml.Api.dll"]
