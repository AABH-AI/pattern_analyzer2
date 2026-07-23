# Deploying the RCA Console on an internal AA server

Goal: the app + backend run 24/7 on a server **inside the AA network** so anyone on the
network/VPN can use the live SQL connection — independent of any laptop. The dataset never
leaves the AA environment.

**Requirement for all options:** the server must have network line-of-sight to the SQL
Server `10.10.9.75` (same as SSMS does), and users reach the app over the AA network / VPN.
It is **not** exposed to the public internet.

---

## Option 1 — Docker (recommended; Windows or Linux)

The image bundles the Microsoft ODBC Driver 18, so nothing else to install but Docker.

1. Copy this repo to the server.
2. Create `.env` in the repo root (next to `docker-compose.yml`) — see `backend/.env.example`:
   ```
   SQL_USERNAME=your_sql_login
   SQL_PASSWORD=your_password
   ```
3. Build & run:
   ```
   docker compose up -d --build
   ```
4. Open on the AA network: **`http://<server-ip>:8000/rca_console.html`** → **Connect to SQL Server (AA)**.

`restart: unless-stopped` keeps it up across reboots. Update later with `git pull && docker compose up -d --build`.

---

## Option 2 — Windows Server without Docker (run as a service)

1. Install **Python 3.11+** and the **ODBC Driver 17 or 18 for SQL Server**.
2. `cd backend && pip install -r requirements.txt`
3. Fill `backend/config.json` (server `10.10.9.75`, database `Playground`, table `dbo.Input_To_ML`,
   `auth: sql`, your username/password, matching `driver`).
4. Install as an always-on service with [NSSM](https://nssm.cc):
   ```
   nssm install RCAConsole "C:\Path\to\python.exe" "-m uvicorn sql_backend:app --host 0.0.0.0 --port 8000"
   nssm set RCAConsole AppDirectory "C:\Path\to\repo\backend"
   nssm start RCAConsole
   ```
5. Allow TCP 8000 through the server firewall (internal only). Access `http://<server-ip>:8000/rca_console.html`.

---

## Option 3 — Linux without Docker (systemd)

1. Install Python 3.11+, `unixodbc`, and `msodbcsql18`.
2. `pip install -r backend/requirements.txt`, fill `backend/config.json`.
3. `/etc/systemd/system/rca.service`:
   ```
   [Unit]
   Description=RCA Console
   After=network.target
   [Service]
   WorkingDirectory=/opt/rca/backend
   ExecStart=/usr/bin/uvicorn sql_backend:app --host 0.0.0.0 --port 8000
   Restart=always
   [Install]
   WantedBy=multi-user.target
   ```
4. `sudo systemctl enable --now rca` · open TCP 8000 internally · access `http://<server-ip>:8000/rca_console.html`.

---

## Notes
- Bind **`0.0.0.0`** (all options above do) so other machines can connect — `127.0.0.1` would be local-only.
- Keep `config.json` / `.env` **secret**; both are gitignored.
- Credentials can be provided by **environment variables** (`SQL_SERVER`, `SQL_DATABASE`, `SQL_TABLE`,
  `SQL_AUTH`, `SQL_USERNAME`, `SQL_PASSWORD`, `SQL_DRIVER`, `SQL_ENCRYPT`, `SQL_TRUST_CERT`) — they
  override `config.json`. That's how the Docker option injects them without a file.
- For HTTPS + a friendly hostname, front it with nginx/IIS reverse proxy (optional).
- Load the demand table once via `python backend/upload_excel_to_sql.py` if it isn't already in SQL.
