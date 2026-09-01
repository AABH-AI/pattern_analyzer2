# Azure provisioning request — Multi-agent RCA Console

> Branch: **`test3_multiagent`**. Image repository: **`rca-multiagent`**. Container port:
> **9402**. This is a *separate* application from the RCA Console on `test3_azure`; the two
> can share a registry and a database but need their own Web App, because each serves its
> own user interface on its own port.

**For:** whoever administers our Azure subscription
**From:** WFM Forecasting
**What this is:** a request to provision four resources so an internal web tool can be hosted
for AA staff. No decisions are needed from you — the values are all specified below.

The application is already built and tested. Our Azure DevOps pipeline builds the container
image and its automated checks pass: the container starts in 2 seconds, serves its UI (HTTP
200), has the SQL ODBC driver installed, and contains no embedded credentials. It has nowhere
to run yet.

---

## What we need

### 1. A container registry

| Setting | Value |
|---|---|
| Resource type | Azure Container Registry |
| SKU | **Basic** (smallest — the image is a few hundred MB) |
| Admin user | **Enabled** — App Service needs it to pull the image, unless you prefer to grant the Web App's managed identity the `AcrPull` role, which is fine and we would prefer |

Please tell us the **login server** afterwards, e.g. `something.azurecr.io`.

### 2. An Azure DevOps service connection

| Setting | Value |
|---|---|
| Where | Azure DevOps → Project settings → Service connections |
| Type | Docker Registry → **Azure Container Registry** |
| Name | **`rca-acr`** — must be this exact string; the pipeline references it. If it already exists for the RCA Console, reuse it; nothing more is needed here |
| Scope | tick *Grant access permission to all pipelines* |

This lets our existing pipeline push the image. It cannot do anything else with the subscription.

### 3. An App Service (Web App for Containers)

| Setting | Value |
|---|---|
| Publish | **Container** |
| OS | **Linux** |
| Plan | **B1** is sufficient. Please avoid Free/F1 — it sleeps, and this app is slow to cold-start |
| Image source | the registry from (1), repository `rca-multiagent`, tag `latest` |

**One application setting is mandatory** (Web App → Configuration → Application settings):

```
WEBSITES_PORT = 9402
```

Without it the site returns a blank page. The container listens on 9402, not 80.

**Please also enable authentication before the URL is shared:**
Web App → Authentication → Add identity provider → **Microsoft** → Workforce →
**Current tenant, single tenant** → *Require authentication*.

This restricts the tool to AA accounts. We are asking for this deliberately: the application
has no login of its own, and one of its endpoints returns the full contents of the data table
to anyone who can reach the URL.

### 4. An Azure SQL Database

| Setting | Value |
|---|---|
| Database name | `rca` |
| Authentication | SQL authentication (an admin login and password) |
| Tier | **Basic** or **S0**. The largest table is 114,436 rows × 32 columns — small |
| Backup redundancy | locally-redundant is fine; the data is reloaded weekly from source |

**Server firewall** (on the server, not the database):

- **Allow Azure services and resources to access this server** → **ON** (so the Web App can connect)
- Add the public IP of the machine that will run the weekly data load — we will tell you which

#### Why a copy of the data is needed

Our source database is at `10.10.9.75`, which is RFC1918 private address space. Azure cannot
route to it, so a cloud-hosted container cannot query it. Either the app runs inside our network
and has no Azure URL, or the data is copied to somewhere Azure can reach. We are asking for the
second.

We have written and tested the copy tool (`backend/migrate_to_azure_sql.py`). It reads from the
internal server, writes to Azure SQL, and verifies row counts per table. It runs from a laptop
on the VPN — never from the pipeline, which cannot see the internal network.

We verified compatibility before proposing this: every SQL construct the application uses is
supported on Azure SQL Database, and none of the usual blockers appears anywhere in the code —
no `USE <database>`, no cross-database joins, no `xp_cmdshell`, `OPENROWSET`, `BULK INSERT`,
linked servers, `FILEGROUP` or `DBCC`. **No application code changes are required.**

---

## Settings we will need to set ourselves afterwards

Once (3) and (4) exist, these go on the Web App. Listing them so you know what to expect; the
two marked secret should ideally come from Key Vault.

| Setting | Value |
|---|---|
| `WEBSITES_PORT` | `9402` |
| `SQL_SERVER` | the Azure SQL server name |
| `SQL_DATABASE` | `rca` |
| `SQL_TABLE` | `dbo.Input_To_ML_Full_138_Trimmed` |
| `SQL_AUTH` | `sql` |
| `SQL_USERNAME` | the login — **secret** |
| `SQL_PASSWORD` | the password — **secret** |
| `SQL_DRIVER` | `ODBC Driver 18 for SQL Server` |
| `SQL_ENCRYPT` | `true` |
| `SQL_TRUST_CERT` | `false` |
| `ALLOWED_ORIGINS` | the Web App's own https URL |

Two optional ones, later, for the AI summary feature. The tool works fully without them — it
produces its complete analysis and states that only the written summary is missing.

| Setting | Purpose |
|---|---|
| `GROQ_API_KEY` | The **only** provider this branch uses. All four roles are Groq-hosted models — **secret** |
| `APP_MODULE` | Leave unset. Defaults to `agents.server:app`. Set to `sql_backend:app` only to serve the original single-engine console from this same image instead |

---

## What this does not need

Stated so the request can be scoped tightly:

- **No inbound firewall changes** and no VPN or ExpressRoute. The container makes only outbound
  connections: to Azure SQL, and optionally to an AI provider over HTTPS.
- **No public database access.** Azure SQL stays behind its firewall, reachable only by Azure
  services and the one IP that loads data.
- **No Kubernetes.** It is a single container. App Service is sufficient.
- **No custom domain or certificate** initially. `*.azurewebsites.net` with its managed
  certificate is fine to start.
- **No data leaves the tenant** beyond the AI provider calls, and those are optional and off by
  default. They send analysis text and figures, never raw table extracts.

## Rough monthly cost

App Service B1 + Azure SQL Basic/S0 + a Basic container registry. All are at the bottom of
their pricing tiers; please check current rates for our region rather than trusting a number
written here.

## If any of this is not permitted

The fallback needs nothing from Azure at all: we run the same container on an internal server
with Docker, using the `docker-compose.yml` already in the repository. The tool then works for
anyone on the AA network or VPN, but has no external URL. Tell us if that is the preferred route
and we will take it instead — we would just rather not, because it keeps the VPN dependency that
prompted this request.

## Verifying it works, once provisioned

```
1.  https://<app>.azurewebsites.net/api/health      -> configured: true
2.  https://<app>.azurewebsites.net/api/data?limit=5 -> returns rows
3.  https://<app>.azurewebsites.net/rca_console.html -> sign-in, then the console loads
```

Full detail, including the weekly refresh procedure, is in `DEPLOY_AZURE.md` in the repository.
