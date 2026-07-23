# Demand Pattern RCA Agent — backend + UI, for internal-server hosting.
# Bundles the Microsoft ODBC Driver 18 so it can reach SQL Server on the AA network.
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

# whole repo (the .html UI lives at repo root; sql_backend serves it)
COPY . /app

WORKDIR /app/backend
EXPOSE 8000
# 0.0.0.0 so other machines on the AA network can reach it
CMD ["uvicorn", "sql_backend:app", "--host", "0.0.0.0", "--port", "8000"]
