# infra

Terraform for the formapp `demo` environment in Azure Southeast Asia. Rules: [`docs/standards/terraform.md`](../docs/standards/terraform.md) and [`docs/standards/azure.md`](../docs/standards/azure.md); binding decisions: spine AD-11.

```text
infra/
  bootstrap/          state-backend.sh + README: one-time manual steps (Owner)
  modules/            thin wrappers the stacks call (resource group, registry, Log Analytics,
                      Application Insights, Container Apps environment, PostgreSQL,
                      user-assigned identity, Foundry)
  demo/foundation/    stack 1: everything long-lived (state key demo/foundation.tfstate)
  demo/agent/         stack 2: per-deploy: the Container App's image and agent env, and the
                      hosted agent (Story 4.1); state key demo/agent.tfstate
```

Pinned versions: Terraform 1.16.4, `azurerm` 5.7.0, `azapi` 2.12.0, `random` 3.9.1. Each root commits its `.terraform.lock.hcl`.

## Apply order

1. **Bootstrap, once per subscription:** `infra/bootstrap/state-backend.sh`. See [`bootstrap/README.md`](bootstrap/README.md).
2. **`demo/foundation`:** `terraform plan -out=tfplan`, owner approves, `terraform apply tfplan` (pipeline only).
3. **Once, after the first foundation apply:** the `pgaadauth_create_principal` step in [`bootstrap/README.md`](bootstrap/README.md#3-postgresql-principals-pgaadauth_create_principal).
4. **Images:** `az acr build` of `api` and `agent` into `crsampledemosea` (pipeline, outside Terraform).
5. **Migrations:** `alembic upgrade head` on the runner (pipeline, outside Terraform).
6. **`demo/agent`:** plan, owner approves, apply the saved plan (pipeline only).
7. **Post-deploy smoke checks:** `/readyz`, then the forged-principal `/api/me` 401 check, then one Responses call to the hosted agent.

A failed step stops the steps after it. Applies never run locally and never with `-auto-approve`; a local `terraform plan` is fine for checking (see [`bootstrap/README.md`](bootstrap/README.md#2-local-plan-verification-only)).

Steps 2 and 4-7 are the **Deploy demo** workflow ([`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)); see [Deploying](#deploying).

## Pull request checks

GitHub Actions runs only **Deploy demo** and **Destroy demo** (owner decision, 2026-09-27, to cut Actions cost). The pull-request checks run locally with [`scripts/check.sh`](../scripts/check.sh) before every push, and the pull request carries its summary:

- **`secrets`:** gitleaks over the full git history (false-positive allowlist in `.gitleaks.toml`).
- **`infra`:** `terraform fmt -check`, `validate` and `terraform test` in the affected roots and modules (the `foundation` root and six modules are skipped, POC only), `tflint` with the root `.tflint.hcl`, `shellcheck`, `actionlint`, and the deploy guard (`scripts/plan-guard.sh`) against its fixtures in `scripts/tests/fixtures/` (`fail-*.json` must be blocked, `pass-*.json` allowed).
- **`plan`** (`--plan`, opt-in): `foundation`, then `agent` (with `-var image_tag=<HEAD>`), both with `-lock=false`, signed in with the local `az login` identity. Read-only; it never applies. Paste the `Plan:` lines into the pull request for any `infra/` change.
- **`api`, `agent`, `web`:** lint and audit (the form-schema lint, tsc, ESLint, Prettier, `npm audit --omit=dev --audit-level=high`) and the tests with their coverage minimums (80% for `api/` and `agent/`, 60% for `web/`), the agent's offline evaluation set, and Playwright (`e2e`) against a throwaway local PostgreSQL container.
- **`api-image`, `agent-image`:** build each image and run the same smoke checks the deploy relies on.

With no section named, the script runs the sections the change touches (compared with `origin/dev`); `--all` runs every section. Both branches still require a pull request, but no status check: the local run is the gate. No plan or state file is ever committed.

## Deploying

Merges never apply. To deploy:

1. Merge the change into `dev` by pull request, then promote `dev` to `main` by pull request. For any `infra/` change, review the `scripts/check.sh --plan` summary pasted into the `main` pull request: it is what the deploy will apply (the deploy plans again and shows its plan in the run summary).
2. In GitHub, **Actions > Deploy demo > Run workflow**, on `main`. Starting the run is the approval. It runs in the `demo` Environment (deployment branch policy: `main` only) and deploys only if its commit is still the `main` HEAD; otherwise it stops before signing in to Azure. One deploy runs at a time.
3. The run, in order, stopping at the first failure:
   1. `foundation` plan, then the guard [`scripts/plan-guard.sh`](scripts/plan-guard.sh), which fails on any destroy or replace of the resource group, PostgreSQL (server or database), the Container Apps environment or a Foundry resource, then the plan in the run summary, then `terraform apply tfplan`.
   2. `az acr build` of `api/Dockerfile` into `crsampledemosea` as `api:<commit SHA>`, then of `agent/Dockerfile` (build context `agent/`) as `agent:<commit SHA>`.
   3. Migrations: `alembic upgrade head` on the runner as `id-sample-demo-sea-deploy` (Entra token, no password), reaching PostgreSQL through the allow-all firewall rule (`postgresql_allow_public_access = true`); there is no per-run firewall rule. If `postgresql_allow_public_access` is set to false, the migration step can't connect, and the per-run firewall steps removed in FORM-7 would have to be restored. Skipped with a note until Story 1.3 adds `api/alembic.ini`.
   4. `agent` plan (in the run summary) and apply: the Container App's image becomes `api:<commit SHA>` with the agent env added, which starts a new revision, and the hosted agent `formapp-agent` gets a new version running `agent:<commit SHA>` (see [The agent stack](#the-agent-stack)). The image patch (`azapi_resource_action`, PATCH) can't detect drift, so every deploy replaces it and sets the image again, even for an unchanged commit.
   5. Smoke check (read-only): within 3 attempts, 10 seconds apart, the latest revision runs the new image, is ready, and `https://<app FQDN>/readyz` returns 200.
   6. Hosted agent smoke check (after `/readyz` and the forged-principal `/api/me` 401 check): one Responses call to `formapp-agent` as the deploy identity, with `store: false` and no turn token. Within 5 minutes (a cold start included) it must answer with the agent's fixed no-token reply, "The AI couldn't finish. Answers so far are saved. Please try again." That reply needs no model call and no MCP call, so it proves the image, its settings and the endpoint without spending tokens.

The pipeline signs in with OIDC as `id-sample-demo-sea-deploy`, using the repository variables `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` and `AZURE_CLIENT_ID` (not secrets). No Azure secret is stored in GitHub.

### First deploy

1. The bootstrap has run and the three repository variables are set ([`bootstrap/README.md`](bootstrap/README.md#values-to-copy)). For an environment bootstrapped before Story 4.1, rerun the bootstrap first: it gives the deploy identity **Foundry User** on `rg-sample-demo-sea`, without which the `agent` apply can't create the hosted agent.
2. Start **Deploy demo** on `main`. The `foundation` apply creates the environment (PostgreSQL takes several minutes), the migration step is skipped, the `agent` stack sets the `api` image and creates the hosted agent from the `agent` image, and the smoke checks run in order: `/readyz`, the forged-principal `/api/me` 401 check, then one Responses call to the hosted agent.
3. Right after it, run the `pgaadauth_create_principal` step in [`bootstrap/README.md`](bootstrap/README.md#3-postgresql-principals-pgaadauth_create_principal). The migration step needs the pipeline's database principal and role, so do this before the first deploy that contains `api/alembic.ini` (Story 1.3).
4. Check the Story 1.1 items that need a live environment (resources, names, tags, AcrPull) and record them in its spec.

Before `foundation` is first applied, the `agent` plan has nothing to change (it waits for `foundation`'s outputs).

**First deploy of Story 4.1** (existing environment): rerun the bootstrap (above), then start Deploy demo. The `foundation` plan adds the Foundry account, project, capability host, model deployment, App Insights connection, diagnostic setting and three role assignments, and replaces nothing (the guard checks it). The `agent` plan then adds the hosted agent and its two role assignments, and the PATCH adds the api's agent env. A second `foundation` plan after the deploy must show no changes.

### Rollback

If the smoke check fails, the new image is running but not ready. The Container App uses single-revision mode, so point it back at the previous image; this creates a new revision from it:

```bash
RG=rg-sample-demo-sea
APP=ca-sample-demo-sea
# Revisions, newest last, with their images.
az containerapp revision list --resource-group "$RG" --name "$APP" \
  --query "sort_by([], &properties.createdTime)[].{revision:name, image:properties.template.containers[0].image, created:properties.createdTime, healthy:properties.healthState}" -o table
# Point the app back at the last image that passed the smoke check.
az containerapp update --resource-group "$RG" --name "$APP" --image "crsampledemosea.azurecr.io/api:<previous SHA>"
```

Then check `https://<app FQDN>/readyz` returns 200. This is the one documented manual change to the Container App. Terraform doesn't see it, but every deploy sets the image again (the agent stack re-applies its image patch each run), so the next deploy of `main` puts the bad image back: fix the cause with a new pull request (or revert the bad one) before deploying again.

If the failed deploy ran a migration, the previous image's `/readyz` fails too, because the database's Alembic revision no longer matches the head in that image (AD-10). Migrations are backward-compatible, so the fix is forward: correct the code and deploy again, rather than rolling the database back.

## What `foundation` creates

| Resource | Name | Notes |
| --- | --- | --- |
| Resource group | `rg-sample-demo-sea` | Adopted from the bootstrap with an `import` block |
| Container registry | `crsampledemosea` | Basic, admin user disabled |
| Log Analytics workspace | `log-sample-demo-sea` | 30-day retention, 0.5 GB/day cap |
| Container Apps environment | `cae-sample-demo-sea` | Consumption; logs to the workspace from creation |
| Container App | `ca-sample-demo-sea` | 1 replica, HTTPS-only ingress, placeholder image; ignores image and env changes (the agent stack sets both) |
| Managed identity | `id-sample-demo-sea-api` | AcrPull on the registry, Monitoring Metrics Publisher on Application Insights (telemetry ingestion), Storage Blob Data Contributor on the `tokenstore` container only (sign-in token store), and Foundry User on the Foundry project (Story 4.1) |
| PostgreSQL flexible server | `pgsql-sample-demo-sea` | 18, `B_Standard_B1ms`, 32 GiB, Entra-only auth, admin group `formapp-db-admins`, secure transport on, Azure-services firewall rule only, 7-day backup, no HA |
| Turn-token signing key | Container App secret `turn-token-signing-key` | `random_password`, exposed to the container as `TURN_TOKEN_SIGNING_KEY`; rotate by changing `turn_token_signing_key_rotation`, applying, then restarting the active revision ([steps](bootstrap/README.md#rotating-the-turn-token-signing-key)) |
| Budget | `budget-sample-demo` | 15/month (billing currency), alerts at 90/100/110% actual and 110% forecast |
| Application Insights | `appi-sample-demo-sea` | Workspace-based on `log-sample-demo-sea`, local authentication off (Entra-authenticated ingestion only); the `api` identity holds **Monitoring Metrics Publisher** on it. Its connection string reaches `api` only as the Container App secret `appinsights-connection-string` (env `APPLICATIONINSIGHTS_CONNECTION_STRING`), never as an output |
| Action group | `ag-sample-demo-sea` | Emails the owner (`budget_alert_emails`) |
| Log cap alert | `ar-sample-demo-sea-log-cap` | Scheduled query on the workspace's `Usage` table every 30 minutes: fires (once, until it clears) when billable ingestion over the last 24 hours reaches 90% of the 0.5 GB cap (450 MB) |
| Token-store storage account | `stsampledemosea` | Story 1.6. AVM `avm-res-storage-storageaccount` (azapi-based). Standard LRS, shared keys (and so SAS) off, public blob access off, TLS 1.2, HTTPS only; one private container `tokenstore` holding signed-in sessions. Reached only with the `api` identity |
| Container Apps authentication | `current` on `ca-sample-demo-sea` | Story 1.6. `azapi` `Microsoft.App/containerApps/authConfigs` (azurerm has no resource for it): Entra provider (single tenant), `AllowAnonymous`, HTTPS only, token store in `tokenstore` through the `api` identity. See [Sign-in (Entra)](#sign-in-entra) |
| PostgreSQL diagnostic setting | `to-log-sample-demo-sea` | `PostgreSQLLogs` only, to the workspace, with `log_error_verbosity = TERSE` on the server. The Container Apps environment has no diagnostic setting: it already sends its logs to the workspace (`logs_destination`), and a second route would duplicate them |

Every name is built in `demo/foundation/locals.tf`; every taggable resource carries the six tags from `local.tags`.

| Foundry account | `aif-sample-demo-sea` | AIServices S0, custom subdomain `aif-sample-demo-sea`, local (key) auth off, system identity, projects enabled; purged, not soft-deleted, on destroy |
| Foundry project | `proj-sample-demo-sea` | System identity, which holds **AcrPull** on the registry to pull the agent image and **Monitoring Metrics Publisher** on Application Insights (Foundry Agent Service's server-side traces run as this identity). Endpoint `https://aif-sample-demo-sea.services.ai.azure.com/api/projects/proj-sample-demo-sea` (output `foundry_project_endpoint`) |
| Capability host | `agents` on the account | Kind `Agents` only, enables Agent Service on the account with Microsoft-managed agent data (azapi; azurerm has no resource for it) |
| Model deployments | `gpt-5.4-mini` (active), `gpt-4.1-mini` (rollback) | gpt-5.4-mini `2026-03-17` and gpt-4.1-mini `2025-04-14`, each Global Standard, capacity 30 (thousand tokens per minute), `NoAutoUpgrade`, default content filter (no custom RAI policy). `foundry_active_model_deployment` picks the active one (FORM-226); to roll back, set it to `gpt-4.1-mini` and deploy. The active name reaches api as `FOUNDRY_MODEL` and the hosted agent as `MODEL_DEPLOYMENT_NAME` (`FOUNDRY_MODEL` is reserved for platform use in the hosted agent container) |
| App Insights connection | `appi-sample-demo-sea-project` on the *project* (`proj-sample-demo-sea`) | `Microsoft.CognitiveServices/accounts/projects/connections` (azapi; azurerm has no resource for it), category `AppInsights`, targeting `appi-sample-demo-sea`, `authType = "ProjectManagedIdentity"` (no API key: Application Insights has local auth off). Foundry injects `APPLICATIONINSIGHTS_CONNECTION_STRING` into the hosted agent, and the Traces tab reads traces, only from a connection on the **project**; an account-level connection (Story 4.1's original wiring) does neither (Microsoft Learn, "Export hosted agent telemetry by using OpenTelemetry" and "Set up tracing for AI agents"). That old account connection, `appi-sample-demo-sea`, is no longer managed by Terraform but still exists (the deploy guard blocks deleting Foundry resources); the project sees it under the same name, hence the `-project` suffix. The owner may delete it in the portal |
| Foundry diagnostic setting | `to-log-sample-demo-sea` | `Audit` and `RequestResponse` logs to the workspace |

**Why some resources are hand-written:** the latest Azure Verified Modules for the registry, Log Analytics, Application Insights, Container Apps environment, PostgreSQL and user-assigned identity all require `azurerm < 5.0`, which can't run with the pinned `azurerm` 5.7.0. Their wrappers in `modules/` use `azurerm` resources until AVM releases support 5.x; the resource group and the token-store storage account use their (azapi-based) AVM modules. The Foundry wrapper (`modules/foundry`) is hand-written for the same reason: `Azure/avm-res-cognitiveservices-account` 0.11.1 requires `azurerm < 5.0`. The Container App is hand-written because a module call can't carry the `lifecycle.ignore_changes` AD-11 needs, and the budget, action group, alert rule and diagnostic setting because no Available AVM module for them runs with `azurerm` 5.x. Each file says why.

## Sign-in (Entra)

Story 1.6. Agents sign in with Microsoft through Container Apps authentication (Easy Auth). The platform signs the user in, strips any client-sent `X-MS-CLIENT-PRINCIPAL` and passes its own to `api`, which reads the `oid` and names from it and answers 401 on every `/api/*` path without one. `/healthz`, `/readyz`, the web files and `/.auth/*` stay public.

**Accepted POC exception:** unauthenticated requests are allowed (`AllowAnonymous`) so the signed-out Welcome page can load; `api` itself enforces sign-in. The Azure Policy audit flags this (azure.md rule 12, security.md section 9).

### 1. Create the app registration (once, by hand)

The pipeline identity has no directory rights, so Terraform never creates the registration; it takes only its client ID. An operator who can create app registrations in the tenant does this once:

1. Azure portal > **Microsoft Entra ID** > **App registrations** > **New registration**.
2. Name: `formapp-demo-signin`. Supported account types: **Accounts in this organizational directory only** (single tenant).
3. Redirect URI: platform **Web**, URI `https://<container_app_fqdn>/.auth/login/aad/callback`, where `<container_app_fqdn>` is the foundation output `container_app_fqdn` (for example `ca-sample-demo-sea.<unique>.southeastasia.azurecontainerapps.io`). Register.
4. **Authentication**: under *Implicit grant and hybrid flows*, tick **ID tokens** (sign-in uses the ID-token flow). Leave access tokens unticked. Save.
5. **Token configuration** > **Add optional claim** > token type **ID** > tick **given_name** > Add (accept the Microsoft Graph `profile` permission prompt if shown). The header greets the user by this first name.
6. **Certificates & secrets**: add nothing. There is no client secret; the turn-token signing key stays the only app secret (azure.md rule 10).
7. **Overview**: copy the **Application (client) ID** into `demo/foundation/terraform.tfvars` as `entra_signin_client_id` (a GUID, not a secret) and merge it through a pull request.
8. Users: the owner creates the synthetic demo users in this directory (no real people's data).

If the Container App is ever recreated with a new FQDN, update the redirect URI in step 3.

### 2. Before the Story 1.6 deploy

Rerun `infra/bootstrap/state-backend.sh`: its RBAC Administrator condition now also allows **Storage Blob Data Contributor** (service principals only), which foundation needs to give the `api` identity the `tokenstore` container. Without it, the foundation apply fails at that role assignment ([`bootstrap/README.md`](bootstrap/README.md)).

The foundation plan then adds the storage account `stsampledemosea`, its `tokenstore` container, the role assignment and the `authConfigs` resource `current`, and changes nothing else destructively.

### 3. Company branding (steps only; not configured yet)

The Microsoft-hosted sign-in page can carry formapp's look. This needs a Microsoft Entra ID P1 or P2 licence, which the tenant doesn't have yet, so it is carried in `deferred-work.md`. When a licence exists:

1. Azure portal > **Microsoft Entra ID** > **Company branding** > **Default sign-in experience** > **Edit**.
2. **Basics**: background image (1920x1080, under 300 KB, no real people's data) that fits the Theme D palette; page background colour `#F1F1F2` (the canvas).
3. **Layout**: template *Full-screen background*; keep the header and footer hidden.
4. **Sign-in form**: banner logo (280x60, the crimson `f` tile with "formapp"), square logo (240x240, the `f` tile); sign-in page text: "Tell the AI about your customer. It fills in the proposal for you to check."
5. Review and save. Check by signing in from the Welcome page.

### Checking sign-in after a deploy

The deploy's smoke check sends a forged `X-MS-CLIENT-PRINCIPAL` to `/api/me` and fails unless it gets 401. By hand: open the app URL signed out (Welcome page), choose **Sign in with Microsoft**, sign in as a synthetic user and land on My proposals with the name in the header; choose the avatar > **Sign out** and land back on Welcome. Sign out ends only the formapp session: the Microsoft (Entra) session stays, so the next **Sign in with Microsoft** on the same device signs the same account in without asking; on a shared device, also sign out of Microsoft (for example at `https://login.microsoftonline.com/logout.srf`) or close the browser.

## The agent stack

`demo/agent` runs on every deploy, after the migrations. It reads `foundation` only through remote-state outputs (terraform.md rules 7-8) and has two gates:

- **`foundation_ready`** (`container_app_id`, `container_registry_login_server`, `api_container`): the Container App exists. The stack then patches its api container with `azapi_resource_action` (PATCH): foundation's `api_container` spec (env with secret names only, probes, sizing) plus the image `api:<commit SHA>`.
- **`foundry_ready`** (also `container_app_fqdn`, `foundry_project_endpoint`, `model_deployment_name`, `hosted_agent_name`, `hosted_agent_role_assignments`): Foundry exists. The stack then also:
  - appends `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_AGENT_NAME` and `FOUNDRY_MODEL` to the api env in the same PATCH (api is a plain Container App, so none of these names are reserved there);
  - creates or updates the hosted agent `formapp-agent` (`azapi_data_plane_resource`, `Microsoft.Foundry/agents@v1`, under the project endpoint): image `agent:<commit SHA>`, 0.5 vCPU / 1 GiB, a 15-minute idle timeout, the Responses protocol 2.0.0 on port 8088, and the env `FORMAPP_MCP_URL` (`https://<app FQDN>/mcp`), `MODEL_DEPLOYMENT_NAME` and `TELEMETRY_SAMPLING_RATIO`. The platform reserves every `FOUNDRY_*`/`AGENT_*` name for itself and rejects the version create (400 `invalid_payload`) if the stack declares one, so `FOUNDRY_PROJECT_ENDPOINT` and `APPLICATIONINSIGHTS_CONNECTION_STRING` are never set here: the platform injects both into the hosted agent container itself, along with `FOUNDRY_AGENT_NAME`, `FOUNDRY_AGENT_VERSION` and others (Microsoft Learn, "Deploy a hosted agent" and "Configure environment variables for a hosted agent"). A changed image or setting makes Foundry create a new agent version; an unchanged commit changes nothing;
  - gives the agent's own Entra identity (`instance_identity.principal_id` on the agent) **Foundry User** on the project and **Monitoring Metrics Publisher** on Application Insights. The container runs as that identity and emits traces from code in the sandbox; the project's system identity separately emits Foundry Agent Service's own server-side traces, pulls the image (AcrPull), and holds Monitoring Metrics Publisher too (both `foundation` roles; the [project's App Insights connection](#monitoring-and-logging) needs it).

Without the Foundry outputs (an older `foundation` state), the stack patches the image as before and plans no hosted agent and no agent env.

**Env ownership.** `foundation` creates the Container App with the env in `local.api_env` and then ignores the whole env list (and the image). Every deploy's PATCH resends `api_container.env`, built from the same `local.api_env`, plus the agent env. So a new or changed api setting goes into `local.api_env` and reaches the app on the next deploy, and a second `foundation` plan after a deploy shows no changes.

### Hosted agent smoke check fails

The deploy's last step prints the HTTP status of each attempt and the last response. Check, in this order:

1. **403:** the deploy identity lacks Foundry User on `rg-sample-demo-sea`. Rerun the bootstrap ([`bootstrap/README.md`](bootstrap/README.md)) and deploy again.
2. **404:** the agent or its endpoint doesn't exist. Check the `agent` apply's log and the Foundry portal (**Agents**) for `formapp-agent`.
3. **An error, or another reply:** read the version's status and error in the Foundry portal (**Agents > formapp-agent > Versions**). `image_pull_failed` means the project identity's AcrPull is missing or the image `agent:<commit SHA>` wasn't built. A container that stops at startup names the missing or invalid setting (never its value) in its log, for example `FORMAPP_MCP_URL`.
4. **Timeouts only:** a cold start can take a few minutes; start Deploy demo again (the plans change nothing, and the smoke check retries).

Rerunning Deploy demo for the same commit sends the same hosted-agent definition, so Foundry creates no new version: a version that failed (for example `image_pull_failed` before the project identity's AcrPull had propagated) is never retried that way. A new version comes only from deploying a new commit (never a local apply; AGENTS.md forbids it).

The api side of the deploy is already live when this step runs; nothing is rolled back automatically.

## Monitoring and logging

`api` sends traces to `appi-sample-demo-sea` through the Azure Monitor OpenTelemetry distro (Story 1.5): request spans (except exactly `/healthz` and `/readyz`), PostgreSQL dependency spans and exceptions (type and frames only, never the message). It is on only when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, so local runs and CI export nothing. `TELEMETRY_SAMPLING_RATIO` (`telemetry_sampling_ratio` in `terraform.tfvars`, 1.0 today) sets the share of traces kept.

Ingestion is Entra-authenticated: Application Insights has local authentication off, so the connection string (instrumentation key and endpoints, still passed as a secret) can't send telemetry on its own. `api` signs its exports with its managed identity (`id-sample-demo-sea-api`, through `AZURE_CLIENT_ID`), which holds **Monitoring Metrics Publisher** on `appi-sample-demo-sea` only; `api` refuses to start in demo with a connection string but no `AZURE_CLIENT_ID`. The pipeline can create that role assignment because the deployment identity's RBAC Administrator condition allows Monitoring Metrics Publisher; an environment bootstrapped before Story 1.5 must rerun the bootstrap first ([`bootstrap/README.md`](bootstrap/README.md)).

Logs are not exported by the distro, so each line is ingested once. Every log line is JSON on stdout with the time (UTC), level, logger, message, `trace_id`, `span_id` and `proposal_id` where there are any; the Container Apps environment ships stdout to the workspace, where the lines are in the `ContainerAppConsoleLogs_CL` table (the JSON is in `Log_s`). `LOG_LEVEL` (`api_log_level` in `terraform.tfvars`, `INFO` today) sets the lowest level written. A redaction filter removes `Authorization` and principal headers, turn tokens, connection strings, database tokens, answer values and raw exception text from every log line. PostgreSQL logs errors with `log_error_verbosity = TERSE`, so the DETAIL, HINT and CONTEXT lines that can quote row values are left out of `PostgreSQLLogs` (some primary error messages can still quote an input value).

`cloud_RoleName` for `api`'s telemetry is `formapp-api`: `api/adapters/telemetry.py` passes `configure_azure_monitor` a `Resource.create({SERVICE_NAME: "formapp-api"})` (the same fixed-in-code approach `agent/formapp_agent/telemetry.py` already used for the agent's own direct exports) instead of relying on the distro's own default, `unknown_service:python`, which is what `union traces, requests, dependencies, exceptions | summarize count() by cloud_RoleName` showed before this fix.

### The hosted agent's own telemetry

The hosted agent (Story 4.2) never sets `APPLICATIONINSIGHTS_CONNECTION_STRING` itself: Foundry injects it, reserved (`agent/formapp_agent/settings.py` only reads it), whenever the project has an Application Insights connection (see the App Insights connection row above), and the platform rejects any attempt to set it in the agent env. Its `cloud_RoleName` needs no fix like `api`'s: the platform fixes a hosted agent's `service.name` to the agent's own name (`formapp-agent`) regardless of any `Resource` the code sets, and `OTEL_SERVICE_NAME` has no effect on it (Microsoft Learn, "Export hosted agent telemetry by using OpenTelemetry"). `agent/formapp_agent/telemetry.py` exports through it with the Azure Monitor OpenTelemetry exporter, authenticating with the agent's own Entra identity (Application Insights has local auth off), sampling at `TELEMETRY_SAMPLING_RATIO` and always with Agent Framework message capture off (chat text, tool arguments and results never reach a span; security.md rule 2). If the variable is missing at startup (for example, the project's App Insights connection is missing or misconfigured), the agent logs one `WARNING` naming the missing variable, never a value, so the container logs show why nothing is exported; it starts and serves turns normally either way.

A turn with no valid turn token (`FAILED_TURN_REPLY`, for example a Foundry playground call with no signed-in user) never reaches the model or the MCP server. The hosting library creates no span of its own for the request (its `create_response` "span" is internal bookkeeping, never an OpenTelemetry span), so without a token no Agent Framework span was created either, and the turn produced no trace at all; `agent/formapp_agent/host.py` now opens its own span for that path (name `agent.turn_refused`, joining the incoming trace context the same way the agent's other spans do), carrying a reason code only, never the client's headers or their values.

### Checking that traces arrive

Run these in the Azure portal: **`appi-sample-demo-sea` > Logs** for the Application Insights table names in the first query, **`log-sample-demo-sea` > Logs** for the workspace tables in the others (there the Application Insights tables are `AppRequests`, `AppDependencies` and `AppExceptions`, with `OperationId` and `TimeGenerated`). The same queries can run with `az monitor app-insights query --app appi-sample-demo-sea --resource-group rg-sample-demo-sea --analytics-query '<query>'` (or `az monitor log-analytics query` for the workspace), with the owner's OK.

A request that reads the database, with its PostgreSQL dependency span (last 30 minutes):

```kusto
requests
| where timestamp > ago(30m)
| project operation_Id, request_time = timestamp, request = name, resultCode, request_ms = duration
| join kind=inner (
    dependencies
    | where timestamp > ago(30m)
    | where type =~ "postgresql"
    | project operation_Id, dependency = name, target, dependency_ms = duration, success
  ) on operation_Id
| order by request_time desc
| take 20
```

A request's log lines, joined by trace ID (the Application Insights operation ID is the trace ID):

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(30m) and ContainerAppName_s == "ca-sample-demo-sea"
| extend entry = parse_json(Log_s)
| extend trace_id = tostring(entry.trace_id)
| where isnotempty(trace_id)
| join kind=inner (
    AppRequests
    | where TimeGenerated > ago(30m)
    | project trace_id = OperationId, request = Name, ResultCode
  ) on trace_id
| project TimeGenerated, level = tostring(entry.level), logger = tostring(entry.logger),
    message = tostring(entry.message), proposal_id = tostring(entry.proposal_id), request, ResultCode, trace_id
| order by TimeGenerated desc
```

Telemetry arrives at all (last 30 minutes):

```kusto
union AppRequests, AppDependencies, AppExceptions
| where TimeGenerated > ago(30m)
| summarize items = count(), latest = max(TimeGenerated) by Type
```

The deploy's smoke check calls only `/readyz`, which isn't traced, and its database queries are never exported. Until Story 1.8 adds the first endpoint that reads the database, the first query returns rows only for a traced request that touches PostgreSQL; the last one proves telemetry reaches Application Insights (any request to a path other than the probes, such as the web app's `/`, is a traced request). Data usually shows within a few minutes.

The log cap alert emails the owner when billable ingestion over the last 24 hours reaches 90% of the workspace's 0.5 GB daily cap. The window is rolling because the cap resets at the workspace's own reset hour (shown on the workspace's **Usage and estimated costs > Daily cap** page), not at midnight UTC. If it fires, find the noisy source with `Usage | where TimeGenerated > ago(1d) | where IsBillable | summarize MB = sum(Quantity) by DataType`: lower `telemetry_sampling_ratio` if it is traces (`AppRequests`, `AppDependencies`; sampling affects traces only), or raise `api_log_level` (for example to `WARNING`) if it is logs (`ContainerAppConsoleLogs_CL`).

## Destroy order

Only the owner decides to destroy (azure.md rule 21), and only through the pipeline: **Actions → Destroy demo → Run workflow** on `main`, typing `rg-sample-demo-sea` to confirm. Never run `terraform destroy` locally (AGENTS.md). The workflow shares Deploy demo's queue, refuses anything but the current `main` HEAD, and destroys `demo/agent` first, then `demo/foundation`, each from a saved destroy plan written to the run summary. Run it with mode `plan` first and read the plans, then with mode `destroy`. Cancel any queued Deploy demo first. Everything in `rg-sample-demo-sea` is deleted, including items Terraform doesn't manage. The state storage and the bootstrap items stay. Destroying `foundation` deletes `rg-sample-demo-sea` and the deployment identity's roles on it, so the owner must rerun `infra/bootstrap/state-backend.sh` before the next pipeline run (see [`bootstrap/README.md`](bootstrap/README.md#destroy-order)).

The `agent` destroy deletes the hosted agent (with its versions and its Entra identity's role assignments) before `foundation` deletes the Foundry account. The account is purged on destroy (`purge_soft_delete_on_destroy`), because a soft-deleted account keeps its name and custom subdomain for 48 hours and blocks the next apply. If a destroy leaves it soft-deleted anyway (for example, a failed run), the owner purges it by hand before the next deploy, with the owner's OK for the `az` call:

```bash
az cognitiveservices account list-deleted --query "[].{name:name, location:location}" -o table
az cognitiveservices account purge --location southeastasia --resource-group rg-sample-demo-sea --name aif-sample-demo-sea
```

If the hosted agent's delete fails with a conflict because sessions are still active, wait for its 15-minute idle timeout and run Destroy demo again.
