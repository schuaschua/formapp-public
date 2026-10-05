# Azure standards: formapp

These rules apply to everything in `infra/` and to any code that talks to Azure. The architecture spine (`_bmad-output/planning-artifacts/architecture/architecture-formapp-2026-09-25/ARCHITECTURE-SPINE.md`) is binding. If a rule here seems to disagree with it, the spine wins, and this file needs fixing.

This is a POC: one `demo` environment, synthetic data only, and compliance and trust are out of scope. Cost matters most, because every dollar costs the user about five times as much.

Citations: "spine AD-n" is the architecture spine. "WAF p. n" and "WAF-AI p. n" are pages in the local PDFs listed under [Where to look deeper](#where-to-look-deeper). CAF links go to Microsoft Learn.

## Naming pattern

Most names follow `<abbr>-sample-demo-sea[-<role>]`. Names that can't contain hyphens (the registry and storage accounts) drop the hyphens. `sea` is this project's short code for Southeast Asia. CAF leaves region codes to each project. Abbreviations come from [CAF resource abbreviations](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations), and the component order comes from [CAF naming](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming).

| Resource | Abbr | Name |
| --- | --- | --- |
| Resource group | `rg` | `rg-sample-demo-sea` |
| Resource group (Terraform state, central for all apps) | `rg` | `rg-tfstate-sea` |
| Container registry | `cr` | `crsampledemosea` |
| Container Apps environment | `cae` | `cae-sample-demo-sea` |
| Container app (api + web) | `ca` | `ca-sample-demo-sea` |
| PostgreSQL flexible server | `pgsql` | `pgsql-sample-demo-sea` |
| Log Analytics workspace | `log` | `log-sample-demo-sea` |
| Application Insights | `appi` | `appi-sample-demo-sea` |
| Foundry account (AIServices) | `aif` | `aif-sample-demo-sea` (also its custom subdomain) |
| Foundry project | `proj` | `proj-sample-demo-sea` |
| Speech account (Cognitive Services, SpeechServices) | `cog` | `cog-sample-demo-sea` (also its custom subdomain) |
| User-assigned managed identity (api) | `id` | `id-sample-demo-sea-api` |
| User-assigned managed identity (pipeline deployment) | `id` | `id-sample-demo-sea-deploy` |
| User-assigned managed identity (speech) | `id` | `id-sample-demo-sea-speech` |
| Storage account (Terraform state, central; one container per app, `formapp` here) | `st` | `stexampletfstatesea` |
| Storage account (sign-in token store; private container `tokenstore` only) | `st` | `stsampledemosea` |
| Storage account (feedback export; private container `feedback-export`) | `st` | `stsamplefbdemosea` |
| Budget | none in CAF | `budget-sample-demo` |
| Azure Monitor action group | `ag` | `ag-sample-demo-sea` |
| Azure Monitor alert rule (scheduled query) | `ar` | `ar-sample-demo-sea-<role>`, e.g. `ar-sample-demo-sea-log-cap` |
| Container Apps Job (nightly feedback) | `caj` | `caj-sample-demo-sea-feedback` |

**Required tags** go on the resource group and on every resource that supports tags. Keys are lowercase, and values are lowercase and exact ([CAF tagging](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-tagging)):

| Key | Value |
| --- | --- |
| `workload` | `formapp` |
| `env` | `demo` |
| `owner` | the responsible person's alias (never a password or other personal data) |
| `managedby` | `terraform` |
| `datatype` | `synthetic` |
| `repo` | the repository URL |

## Rules

### Naming & tagging

1. Build every name in one Terraform `locals` block (or a naming module) from `workload`, `env` and `region_short`. Never hand-type a resource name inside a module call. ([CAF naming](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming))
2. Use only the abbreviations in the table above. Any new resource type takes its abbreviation from the [CAF list](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations), and is added to this table in the same PR.
3. Pass a single `local.tags` map containing the six required tags to every AVM module and resource. Code review rejects any taggable resource that doesn't carry it. (WAF p. 866, WAF p. 550)
4. Never put secrets, personal data or real customer data in names or tags. ([CAF tagging](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-tagging))

### Region & subscription

5. Deploy every resource to `southeastasia`, including the Foundry account, the Log Analytics workspace and Application Insights. `location` must come from a variable whose default is `southeastasia`. (spine AD-11, WAF p. 816, WAF p. 1126)
6. Deploy only to the user's existing subscription. Take the subscription ID from `ARM_SUBSCRIPTION_ID`, and never hard-code it in committed code. A new subscription means revisiting access to the deployed models (gpt-5.4-mini, gpt-4.1-mini) first. (spine AD-11, Deferred)

### Identity & secrets

7. Services authenticate with managed identity only. `api` uses a user-assigned identity for PostgreSQL (Entra auth) and for the Foundry agent's Responses endpoint. (spine AD-5, AD-10, WAF p. 861)
8. Turn off key and password auth where Azure lets you: set Foundry `disableLocalAuth = true`, PostgreSQL to Entra-only authentication, and the ACR admin user to disabled. (spine AD-10, WAF p. 862, WAF p. 943)
9. Grant runtime identities only these data-plane roles: **Foundry User** for `api` on the project, **Monitoring Metrics Publisher** for `api` on Application Insights (Entra ingestion; local authentication off), **Storage Blob Data Contributor** for `api` on the sign-in token-store container only (never the account), **Storage Blob Data Contributor** for `api` on the `feedback-export` container of its own dedicated storage account only (Story 7.1/FORM-237, AD-20; storage account dedicated by FORM-240 so Power BI's per-account credential test never lists the sign-in token store's container; the nightly feedback job runs as this same identity), **AcrPull** for each identity that pulls images, and **Cognitive Services Speech User** for the dedicated speech identity on the Speech account only (Story 6.1, AD-19; never for `api`'s own identity). The Foundry project's own system identity gets **AcrPull** on the registry (it pulls the agent image) and, because Foundry Agent Service emits the hosted agent's server-side traces under that same identity, **Monitoring Metrics Publisher** on Application Insights too. The hosted agent's own Entra identity (which the container runs as, and which emits traces from code running in the sandbox) separately gets **Foundry User** on the project and **Monitoring Metrics Publisher** on Application Insights (Story 4.1, 4.2's telemetry fix; both identities need the role because hosted-agent traces come from both). Runtime identities never get Owner, Contributor, or roles scoped to the subscription. The pipeline's deployment identity is the one exception, with the resource-group roles in rule 31. (spine AD-5, WAF p. 258)
10. The only application secret is the turn-token signing key, and it lives as a Container Apps secret. Never put it or any other secret in images, git, `.tfvars`, logs or model context. (spine AD-4, WAF p. 307)

### Networking

11. Use public endpoints with platform TLS. Container app ingress must be HTTPS-only (`allowInsecure: false`). (spine Deferred, WAF p. 861)
12. Turn on Container Apps authentication (Entra) with unauthenticated requests allowed (`AllowAnonymous`), so the signed-out Welcome page can load. `api` itself returns 401 for every `/api/*` route without a signed-in principal. The web app sends signed-out users to the Welcome page, whose button goes to `/.auth/login/aad`. `/mcp` accepts only the turn token. The Azure Policy audit will flag `AllowAnonymous`; this is a known POC exception. (spine AD-4, AD-8, WAF p. 869)
13. The PostgreSQL firewall allows only Azure services by default; development environments may have their firewall open to all addresses for a temporary period (owner policy, 2026-09-27): `postgresql_allow_public_access = true` opens it to any IPv4 address, with Entra-only auth and verified TLS still required; set it to false to close. It also gets a temporary operator IP rule for the `pgaadauth_create_principal` bootstrap, which you delete as soon as the bootstrap is done. The deploy workflow's migration step has no per-run firewall rule of its own; it reaches PostgreSQL through the allow-all rule. If `postgresql_allow_public_access` is set to false, the migration step can't connect, so the per-run firewall steps removed in FORM-7 would have to be restored (terraform.md rule 36). Keep `require_secure_transport` on and connection throttling enabled. (spine AD-10, AD-11, WAF p. 944, WAF p. 948)

### Observability

14. Use exactly one Log Analytics workspace and one workspace-based Application Insights instance, in the same region. Connect the Foundry project to that Application Insights instance. (spine Consistency Conventions, WAF p. 814, WAF p. 816)
15. Send diagnostic settings for the Container Apps environment, PostgreSQL and Foundry to that workspace, with only the log categories you need. Don't add duplicate settings. (WAF p. 1126, WAF p. 1131)
16. Configure OpenTelemetry sampling in `api` and `agent`, and never log turn tokens, `Authorization` headers or connection strings. (spine AD-4, WAF p. 815, WAF p. 861)

### Cost

17. Create a resource-group budget in `foundation`, with actual-cost alerts at 90%, 100% and 110%, plus a forecast alert at 110%, all sent to the owner. (spine AD-11, WAF p. 386-387)
18. Give the Log Analytics workspace a daily cap (start at 0.5 GB/day) with an alert when usage reaches 90% of the cap, and set retention to the 30-day minimum. (WAF p. 816, WAF p. 1133, WAF p. 430)
19. Use the cheapest tier that works. That means Container Apps on the Consumption profile, PostgreSQL on Burstable with the smallest storage (storage can't be scaled down), ACR Basic, and a mini model (gpt-5.4-mini) on Global Standard pay-per-token with low deployment capacity (TPM). Any higher tier needs a PR note saying why. (spine Stack, WAF p. 863, WAF p. 944-945)
20. Keep the spine's compute ceilings: one `api` replica, the hosted agent at 0.5 vCPU / 1 GiB with a 15-minute idle timeout, and at most 3 chat turns per insurance agent in any 10 seconds (spine AD-9). (spine AD-9, AD-11, Structural Seed)
21. Never destroy the environment automatically or on an agent's initiative. The owner decides when to destroy it; when they do, destroy the `agent` stack, then the `foundation` stack, keeping the state storage. The data is synthetic, and Terraform recreates everything. (WAF p. 431, WAF-AI p. 112)

### Reliability (POC-appropriate)

22. Configure startup, readiness and liveness probes on the container app. `api` never runs migrations at startup; readiness fails unless the database's schema revision equals the Alembic head bundled in the image. (spine AD-10, WAF p. 858-859)
23. Use the Flexible Server default backups (7-day point-in-time restore), with no high availability. (spine Deferred, WAF p. 945)

### AI / Foundry specifics

24. Pin every model deployment's version with auto-upgrade off (`NoAutoUpgrade`); the active one is `gpt-5.4-mini` version `2026-03-17` (owner decision, 2026-09-27, FORM-226), with `gpt-4.1-mini` `2025-04-14` kept for rollback until it is removed. The deployment name reaches code only as configuration. Switch models by adding a deployment and changing the active one, never by replacing a deployment in place, and plan each swap before its model retires (gpt-5.4-mini: 2027-09-21; gpt-4.1-mini: 2027-04-14). (spine Stack, Config, Deferred; WAF-AI p. 35, WAF-AI p. 114)
25. Keep the default content filter (RAI policy) on the deployment, and never attach a custom policy that weakens it. (WAF-AI p. 45)
26. The agent's only tools are the seven MCP tools in AD-3, over `MCPStreamableHTTPTool`, with no other Foundry tools or connections. Submitting stays a human action. (spine AD-1, AD-3, WAF-AI p. 27-28)
27. Keep the agent's prompts in `agent/` under version control, together with a scenario evaluation set that checks tool-call accuracy. Run the set before changing the prompt or the model. (WAF-AI p. 35, WAF-AI p. 118-119)

### Terraform-on-Azure interplay

28. Use Azure Verified Modules (`Azure/avm-res-*`, versions pinned) first, then hand-written `azurerm`, and `azapi` only where `azurerm` doesn't model the resource (the hosted-agent version, `authConfigs`), plus the one exception in terraform.md rule 12. `authConfigs` uses GA API `2026-07-01` with schema validation off for that resource (terraform.md rule 9, security.md section 9). Never use provisioners. (spine AD-11)
29. Keep the state backend in the central account `stexampletfstatesea` (container `formapp`), using Entra auth (`use_azuread_auth = true`), shared-key access disabled, and blob versioning on. `foundation` and `agent` share values only through remote-state outputs. `foundation` owns the Container App and, after creating it, ignores its image and its whole environment variable list; `agent` sets both with `azapi_resource_action` (`PATCH`), resending the env from foundation's `api_container` output plus the agent environment variables. (spine AD-11)
30. Apply in the spine order (`foundation`, then `az acr build`, then database migrations, then `agent`, then a smoke check), and a human approves every plan. Any manual step, such as the PostgreSQL principal bootstrap, is recorded in `infra/README`. (spine AD-11, WAF p. 865)
31. The bootstrap script, run once by an operator who holds Owner, creates `rg-sample-demo-sea` with the six required tags, registers the resource providers the stacks use, and creates the deployment identity `id-sample-demo-sea-deploy` in the state resource group with federated credentials for this repository's `pull_request` and `environment:demo` subjects, using the repo's GitHub OIDC subject prefix read from GitHub's API (an immutable `repo:<owner>@<id>/<repo>@<id>` prefix for this repo), never built from the repo name. That identity holds exactly **Contributor** on `rg-sample-demo-sea`; **Role Based Access Control Administrator** on `rg-sample-demo-sea`, with a condition that it can assign or remove only AcrPull, Foundry User, Monitoring Metrics Publisher, Storage Blob Data Contributor and Cognitive Services Speech User (Story 6.1), and only for service principals; **Storage Blob Data Contributor** on the state container; and **Foundry User** on `rg-sample-demo-sea`, for the Foundry data plane (creating the hosted agent and the deploy's smoke call; Story 4.1, owner decision 2026-09-26). It has nothing at subscription scope, no Owner and no directory rights. `foundation` adopts the resource group with an `import` block, and the `azurerm` provider sets `resource_provider_registrations = "none"`. (spine AD-11)

## Not applied in the POC

| Not applied | Revisit when |
| --- | --- |
| Availability zones, 3+ replicas | Real users or an uptime target (SLO) are agreed (WAF p. 857) |
| Private endpoints, VNet integration, NSGs, egress control | Real data, or compliance comes into scope (spine Deferred, WAF p. 860) |
| Key Vault for secrets and keys | More than one secret, or a key rotation requirement (spine Deferred, WAF p. 862) |
| AI gateway (API Management) with per-user rate limits and token quotas | A second agent client, or the standalone chat app, ships (spine Deferred, WAF-AI p. 39) |
| PostgreSQL high availability, Azure Backup vault | Real data, or a recovery target is set (spine Deferred, WAF p. 942) |
| Azure Policy tag enforcement, Defender for Cloud | A second environment, or a shared subscription owner asks for it (WAF p. 866) |

## Where to look deeper

- `docs/standards/azure/azure-well-architected.pdf` has these service guides: Container Apps p. 856, PostgreSQL p. 941, Application Insights p. 810, Log Analytics p. 1124, and cost alerts p. 386.
- `docs/standards/azure/azure-well-architected-ai.pdf` covers the AI architecture pattern (p. 21), application design (p. 30), operations (p. 110) and testing and evaluation (p. 117).
- The PDFs are a local reference only, and they go out of date. Check the online versions before acting: [Well-Architected Framework](https://learn.microsoft.com/azure/well-architected/), [AI workloads](https://learn.microsoft.com/azure/well-architected/ai/), and [service guides](https://learn.microsoft.com/azure/well-architected/service-guides/).
- CAF: [abbreviations](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations), [naming](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming), [tagging](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-tagging).
