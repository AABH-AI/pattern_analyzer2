# Multi-agent RCA — backend + UI, for container hosting.
# Bundles the Microsoft ODBC Driver 18 so it can reach SQL Server on the AA network.
#
# WHAT THIS SERVES
# ----------------
# This branch's product is the multi-agent console, so the default application is
# agents.server:app, which serves agents_console.html at "/" and the /api/* endpoints.
# The original single-engine app is one environment variable away:
#     APP_MODULE=sql_backend:app
#
# PORT is read from the environment because Azure Container Apps and App Service assign it
# rather than letting the image choose. 9402 matches the local development port.
#
# SECRETS NEVER ENTER THIS IMAGE. `COPY . /app` is guarded by .dockerignore at the repo root,
# which excludes backend/config.json and every backup of it. Credentials arrive as environment
# variables at run time; sql_backend.load_config prefers the environment over the file.
FROM python:3.11-slim

# Microsoft ODBC Driver 18 for SQL Server (Debian 12 / bookworm)
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg apt-transport-https ca-certificates \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && echo "deb [arch=amd64,armhf,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql18 unixodbc \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# whole repo (both .html consoles live at repo root and are served from there)
COPY . /app

WORKDIR /app/backend

ENV APP_MODULE=agents.server:app \
    PORT=9402 \
    PYTHONUNBUFFERED=1

EXPOSE 9402

# Shell form, so PORT and APP_MODULE expand. 0.0.0.0 so the container is reachable.
CMD uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$PORT"
