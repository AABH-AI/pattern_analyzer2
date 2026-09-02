# Getting a shareable link

What it takes to turn this branch into a URL a colleague can open, with the database and the
language model both connected.

---

## First, the thing that trips everyone up

**Azure DevOps cannot host the application.** It does source control, pipelines and build
artifacts. A running web application with a public address is *Azure* — App Service or Container
Apps — and Azure DevOps only pushes to it. So there is no setting in Azure DevOps that produces
a link. Something has to be provisioned in Azure, by someone with rights to do it.

---

## What is already done

| | Status |
|---|---|
| Application containerised | Done — `backend/Dockerfile`, serves the console on port 9402 |
| Secrets kept out of the image | Done — `.dockerignore`, enforced by the build |
| Reads all config from environment variables | Done, and **verified empirically**, not just intended |
| Build + smoke test on every commit | Done — `azure-pipelines.yml`, running now |
| Downloadable build evidence | Done — published as a pipeline artifact |
| Push + deploy pipeline | Written and validated — `azure-pipelines-deploy.yml`, waiting on the items below |
| Data copy tool for Azure SQL | Written — `backend/migrate_to_azure_sql.py` |

The application takes every credential from the environment. A container with **no
`config.json` at all** runs correctly. Confirmed by running it with `SQL_*` and `GROQ_API_KEY`
set and watching them override the file:

```
SQL_SERVER   -> azure-test.database.windows.net   (from env, beat the file)
SQL_USERNAME -> envuser                           (from env)
SQL_PASSWORD -> ********                          (from env)
GROQ_API_KEY -> used, source reported as "GROQ_API_KEY"
```

That is the whole basis of the deployment: secrets arrive as Web App application settings and
exist only in the running container's environment.

---

## The real blocker is the database, not the permissions

The internal SQL Server sits at **`10.10.9.75`**, which is RFC1918 private address space. An Azure Web App
cannot route to it. This is addressing, not configuration — no application setting fixes it, and
no amount of firewall rules on the internal server will help, because the packets have nowhere to
go.

Two ways out. Pick one before provisioning anything else.

### Route A — copy the data into Azure SQL *(recommended, and already tooled)*

The engine reads ten tables. The largest is 114,436 rows by 32 columns, which is small.

```bash
cd backend
export AZURE_SQL_SERVER=rca-sql.database.windows.net
export AZURE_SQL_DATABASE=rca
export AZURE_SQL_USERNAME=<admin login>
export AZURE_SQL_PASSWORD=<its password>

python migrate_to_azure_sql.py --check     # shows what would move, writes nothing
python migrate_to_azure_sql.py --apply     # creates the schema and copies every row
```

Run it **from a laptop on the VPN with internet access** — it needs to see both ends at once. It
can never run in the pipeline, because a hosted build agent cannot see the internal server.

Reload weekly with `--apply --refresh`, which replaces the data and leaves the schema alone.

### Route B — connect Azure back to the internal network

VNet integration plus a site-to-site VPN or ExpressRoute to the AA network. No data copy, and
the console reads live production. Considerably more work, needs network-team involvement, and
carries an ongoing gateway cost. Choose this only if a nightly-fresh copy is genuinely not
acceptable.

---

## What an Azure administrator needs to create

Five things. Roughly 20 minutes if the subscription already exists.

1. **Container registry** — Azure Container Registry, **Basic** tier. The image is a few hundred
   megabytes because it bundles the Microsoft ODBC driver.

2. **Registry service connection** — Azure DevOps → Project settings → Service connections →
   *Docker Registry* → *Azure Container Registry*. Name it exactly **`rca-acr`**. Tick *Grant
   access permission to all pipelines*.

3. **Azure Resource Manager service connection** — same screen, type *Azure Resource Manager*.
   Name it exactly **`rca-azure-subscription`**.

4. **Web App for Containers** — Linux, publish *Container*, plan **B1** or better. Name it
   **`rca-multiagent`**. Avoid Free/F1: it sleeps, and this app is slow to cold-start.

5. **Variable group** — Azure DevOps → Pipelines → Library → *Variable group* named
   **`rca-secrets`**, with the padlock ticked on every value:

   | Name | Value |
   |---|---|
   | `SQL_SERVER_HOST` | `rca-sql.database.windows.net` |
   | `SQL_USERNAME` | the Azure SQL admin login |
   | `SQL_PASSWORD` | its password |
   | `GROQ_API_KEY` | the company Groq key |

   Then grant it access to pipelines. Everything non-secret — port, table name, driver, encryption
   flags — is already in `azure-pipelines-deploy.yml` and needs no editing.

If an Azure SQL Database is being created for Route A: **Basic** or **S0** tier, SQL
authentication, and under *Networking* enable **“Allow Azure services and resources to access
this server”** — without it the Web App is refused at the firewall and the console reports the
database as unreachable.

---

## Then

Register `azure-pipelines-deploy.yml` as a pipeline (Pipelines → New → Existing YAML file) and
run it. It is manual-only on purpose — deployment should be a decision, not a side effect of a
commit. It pushes the image, deploys it with all fourteen application settings, waits out the
cold start, and then reports two separate things:

- whether the site answers, and
- whether it can actually reach the database

A deploy that serves a page but cannot see SQL looks successful and is not, so those are checked
and reported separately.

The link will be **`https://rca-multiagent.azurewebsites.net`**.

---

## "There's a Releases button — can we just release it there?"

Reasonable question, and Releases *is* a deployment mechanism. It will not get you there any
faster, for three reasons.

**It needs the same things that are missing.** A release stage deploying to App Service requires
an Azure Resource Manager service connection, a Web App to deploy to, and a registry holding the
image. None of those exist yet, so the template's service-connection dropdown is empty and the
stage cannot be configured. Releases is a different front-end for the same work — it does not
create Azure resources.

**Do not attach this repository's build artifact to it.** The artifact the build publishes
(`multiagent-rca-<BuildId>`) is *evidence and documentation* — the health response, the endpoint
sweep, the registered routes, `BUILD_SUMMARY.md`, and these markdown files. It is deliberately
not a deployable application. For a container deployment the deployed thing is the **image in the
registry**, referenced by tag; a classic release can do that with no artifact attached at all.
Wiring the evidence artifact in produces a release that ships markdown.

**The work is already written, in the current format.** `azure-pipelines-deploy.yml` does the
push and the deploy with all fourteen application settings, and it is validated. Classic release
pipelines are the older, UI-configured mechanism; YAML multi-stage pipelines are what new work in
Azure DevOps uses. Building the same thing again by hand in the Releases UI means maintaining it
in two places and hand-retyping fourteen settings, including four secrets.

**If your team would still rather click than edit YAML**, that is a legitimate preference and the
route works. Once an administrator has created the resources listed above: New release pipeline →
*Azure App Service deployment* template → set **App type** to *Web App for Containers (Linux)* →
pick the `rca-azure-subscription` connection and the `rca-multiagent` app → set the image to
`<registry>/rca-multiagent:latest` → then add every setting from the `appSettings` block of
`azure-pipelines-deploy.yml` under *Application and Configuration Settings*, and link the
`rca-secrets` variable group under *Variables*. Skip the artifact entirely.

Either way the administrator step comes first. That is the only thing actually blocking a link.

---

## Four things that will otherwise waste an afternoon

**`WEBSITES_PORT` must be 9402.** The container listens on 9402, not 80. Without this setting
Azure probes the wrong port and serves a blank page with no useful error. Already set by the
deploy pipeline.

**The ODBC driver version differs between laptop and container.** `backend/config.json` says
*ODBC Driver 17* because that is what the development machines have. The image installs
**driver 18**. Carrying 17 into the container produces `Can't open lib 'ODBC Driver 17 for SQL
Server'` and a connection that never succeeds. The deploy pipeline sets 18 explicitly.

**Azure SQL encryption settings are the opposite of the internal server's.** Azure SQL requires
`Encrypt=yes` and presents a real certificate, so `TrustServerCertificate` must be **no**. The
values in `docker-compose.yml` are correct for the internal server and wrong for Azure. The
deploy pipeline sets `SQL_ENCRYPT=true` and `SQL_TRUST_CERT=false`.

**Never enable a deploy stage inside `azure-pipelines.yml`.** Azure DevOps resolves service
connections when a run is *queued*, before any `condition:` is evaluated, so a pipeline that
merely mentions a connection which does not exist yet is invalid and cannot run at all. That is
why deployment lives in its own file, and why the build pipeline has nothing commented out.

---

## Cost, roughly

Basic registry, B1 App Service plan and a Basic Azure SQL database land somewhere around USD 40–60
per month at list price — confirm against current pricing for your region rather than quoting this
figure onward. The Groq usage is separate and small — this engine spends about 9,000
tokens per investigation.

## One limit worth stating to whoever asks

With Route A the console reads a **copy** of production, as fresh as the last time
`migrate_to_azure_sql.py --apply --refresh` was run. For explaining a forecast miss in a week
that has already closed, that is fine. If someone needs to investigate the current week live,
they need Route B or the local install.
