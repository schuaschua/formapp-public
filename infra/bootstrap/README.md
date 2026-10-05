# Bootstrap (one-time, manual)

Two manual steps sit outside Terraform (terraform.md rule 29, azure.md rules 29-31):

1. [`state-backend.sh`](#1-run-state-backendsh): before the first `terraform init`.
2. [The PostgreSQL principal step](#3-postgresql-principals-pgaadauth_create_principal): once, after the first `foundation` apply.

The full apply order is in [`../README.md`](../README.md).

## 1. Run `state-backend.sh`

**Who:** an operator who holds **Owner** on the subscription, signed in as a user with the az CLI.

```bash
az login
infra/bootstrap/state-backend.sh            # uses the current az subscription
infra/bootstrap/state-backend.sh <sub-id>   # or pick one explicitly
```

The script stops before creating anything if you are not signed in, are signed in as a service principal, or don't hold Owner. Every item is "show, else create": run it again at any time; a rerun prints `exists` for every item and changes nothing, except that an RBAC Administrator assignment with an outdated condition is deleted and recreated with the current one (printed as `deleted` and `updated`). If a step fails, the script names it and exits non-zero; fix the cause and rerun.

It creates, all in `southeastasia`:

| Item | Name | Notes |
| --- | --- | --- |
| State resource group (central, shared by all apps) | `rg-tfstate-sea` | Tags: `workload=tfstate`, `env=shared`, `managedby=bootstrap`; also holds each app's deployment identity |
| State storage account (central) | `stexampletfstatesea` | Shared-key access off, blob versioning on, TLS 1.2, no public blob access (`sttfstatesea` is taken globally) |
| State container | `formapp` (one container per app) | Keys: `demo/foundation.tfstate`, `demo/agent.tfstate`; roles are scoped to this container only |
| Operator state access | Storage Blob Data Contributor on the `formapp` container | For the signed-in operator, so a local `terraform plan` can read state (Entra auth; no keys) |
| Demo resource group | `rg-sample-demo-sea` | The six required tags with `managedby=terraform`; `foundation` adopts it with an `import` block |
| Resource providers | `Microsoft.App`, `ContainerRegistry`, `OperationalInsights`, `Insights`, `AlertsManagement`, `DBforPostgreSQL`, `ManagedIdentity`, `CognitiveServices`, `Consumption`, `Storage` | The `azurerm` provider sets `resource_provider_registrations = "none"`, so the pipeline never needs subscription rights |
| PostgreSQL admin group | Entra security group `formapp-db-admins` | The operator is added as a member; the group is the server's Entra administrator |
| Feedback readers group | Entra security group `formapp-feedback-readers` | Storage Blob Data Reader at account scope on the dedicated `stsamplefbdemosea` (Story 7.1/FORM-237, FORM-240, AD-20) once it exists -- tolerant: prints a note and skips it if the account isn't there yet. Deletes the group's leftover grant on the removed `stsampledemosea/feedback-export` container |
| Deployment identity | `id-sample-demo-sea-deploy` (in the state resource group) | See below |

### The deployment identity

`id-sample-demo-sea-deploy` is the identity GitHub Actions signs in as (OIDC workload identity federation, no stored secrets). Its federated credentials trust only:

- `repo:example-org@00000000/formapp@0000000000:pull_request` (plan on pull requests)
- `repo:example-org@00000000/formapp@0000000000:environment:demo` (the owner's manual deploy run on `main`, in the `demo` Environment)

The prefix is GitHub's immutable subject (owner and repo IDs), used for repos created or transferred after 2026-07-15. The script reads it from `gh api repos/example-org/formapp/actions/oidc/customization/sub`, so it needs `gh` signed in with access to the repo. If an existing credential trusts a different subject, the script stops and prints the delete command to run first.

It holds exactly four role assignments, and nothing at subscription scope, no Owner and no directory rights (azure.md rule 31, NFR16):

| Role | Scope | Why |
| --- | --- | --- |
| Contributor | `rg-sample-demo-sea` | Create and change the environment's resources |
| Role Based Access Control Administrator, with a condition | `rg-sample-demo-sea` | Terraform's role assignments. The condition allows writing or deleting only **AcrPull**, **Foundry User**, **Monitoring Metrics Publisher**, **Storage Blob Data Contributor** and **Cognitive Services Speech User** assignments, and only for principal type `ServicePrincipal`. Role IDs are resolved by name at run time |
| Storage Blob Data Contributor | the `formapp` container in `stexampletfstatesea` | Read and write Terraform state (this app only) |
| Foundry User (formerly Azure AI User) | `rg-sample-demo-sea` | Story 4.1: create and update the hosted agent through the Foundry data plane (Contributor has no data-plane rights), and the deploy's smoke call to it. The script shows whichever display name the tenant uses |

The script checks this at the end and fails if the identity has any other assignment. The operator's own Storage Blob Data Contributor on the container (above) is separate from these four.

Because of the condition, every `azurerm_role_assignment` in Terraform must set `principal_type = "ServicePrincipal"`.

**Existing environments (Story 1.5):** Monitoring Metrics Publisher was added to the condition so the foundation stack can give the `api` identity that role on Application Insights (telemetry ingestion with Entra auth). An environment bootstrapped before Story 1.5 must rerun `infra/bootstrap/state-backend.sh` before the next deploy: the script replaces the RBAC Administrator assignment with the new condition. Without it, the foundation apply fails when it creates that role assignment, because the old condition refuses it.

**Existing environments (Story 1.6):** Storage Blob Data Contributor was added to the condition so the foundation stack can give the `api` identity that role on the sign-in token-store container (`tokenstore` in `stsampledemosea`). Rerun `infra/bootstrap/state-backend.sh` before the Story 1.6 deploy, for the same reason as above.

**Existing environments (Story 4.1):** Foundry User on `rg-sample-demo-sea` was added so the `agent` stack can create the hosted agent and the deploy can smoke-test it. An environment bootstrapped before Story 4.1 must rerun `infra/bootstrap/state-backend.sh` before the first deploy of Story 4.1: the script adds the fourth assignment (printed as `created`) and checks all four. Without it, the `agent` apply fails with a 403 from the Foundry data plane when it creates the hosted agent. The RBAC Administrator condition is unchanged: it already allows AcrPull, Foundry User and Monitoring Metrics Publisher.

**Existing environments (Story 6.1):** Cognitive Services Speech User was added to the condition so the foundation stack can give the dedicated speech identity that role on the Speech account (AD-19). Rerun `infra/bootstrap/state-backend.sh` before the Story 6.1 deploy: the script replaces the RBAC Administrator assignment with the new condition (printed as `deleted` and `updated`). Without it, the foundation apply fails with `AuthorizationFailed ... ABAC condition that is not fulfilled` on `azurerm_role_assignment.speech_user` (seen in run 36367567415, 2026-09-28).

**Existing environments (Story 7.1/FORM-237):** the script now also creates the Entra group `formapp-feedback-readers` and, once the `feedback-export` container exists, gives it Storage Blob Data Reader on that container only (AD-20). This role isn't in the deployment identity's RBAC Administrator condition and doesn't need to be: the script assigns it directly, as the operator, to a Group principal -- the condition only ever governs assignments the deployment identity itself makes, and it may only target service principals. Rerun the script once after the Story 7.1 deploy (`foundation` creates `feedback-export`); a run before that just prints a note and skips the role assignment.

**Existing environments (FORM-240):** Power BI records a Blob source by storage account and, when saving credentials, test-lists every container on it; with `feedback-export` and the sign-in token store's `tokenstore` on the same account, `formapp-feedback-readers`'s container-scoped Reader made that test fail and Power BI reject the credentials. `foundation` now creates a dedicated `stsamplefbdemosea` for `feedback-export` alone, and the script grants `formapp-feedback-readers` Storage Blob Data Reader at that account's scope (harmless here: the account holds nothing else). The old container on `stsampledemosea` was then removed (owner, 2026-09-28); the script deletes the group's leftover grant on it. Rerun the script once after the FORM-240 deploy; a run before that just prints a note and skips the new role assignment.

### Values to copy

At the end the script prints (none of them are secrets):

- `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_CLIENT_ID`: GitHub repository **variables** (never secrets) for the pipeline's OIDC sign-in, used by `.github/workflows/ci.yml` (plans) and `deploy.yml`. Set each with `gh variable set <NAME> --repo example-org/formapp --body <value>` and check with `gh variable list --repo example-org/formapp`.
- `db_admin_group_object_id`: paste it into `infra/demo/foundation/terraform.tfvars` in a pull request. Plan refuses to run while it is the all-zero placeholder.

## 2. Local plan (verification only)

Applies run only from the pipeline's deploy workflow, which the owner starts by hand on `main`. Locally you may only plan:

```bash
export ARM_SUBSCRIPTION_ID=<subscription id>
cd infra/demo/foundation
terraform init
terraform plan -out=tfplan
```

Expect: the resource group **imported** (not created), everything else created, nothing destroyed. Never run `terraform apply` or `destroy` locally, and delete `tfplan` afterwards (it is gitignored).

## 3. PostgreSQL principals (`pgaadauth_create_principal`)

Run once, after the first `foundation` apply. It makes both managed identities database principals, creates the migration role and grants it only to the pipeline identity (AD-10, AD-11, AD-17, azure.md rules 13 and 30).

**Who:** a member of `formapp-db-admins` (the bootstrap operator). Needs `psql`.

### 3.1 Open a temporary firewall rule for your IP

The commands below use the older Azure CLI form (`--name` is the server). Newer CLI versions, like the one on GitHub's runners, use `--server-name` for the server and `--name` for the rule (no `--rule-name`); switch if `az` asks for `--server-name`.

The server only allows Azure services (azure.md rule 13), so add a rule for your public IP for the duration of this step:

```bash
RG=rg-sample-demo-sea
PG=pgsql-sample-demo-sea
MY_IP=$(curl -fsS https://api.ipify.org)
az postgres flexible-server firewall-rule create --resource-group "$RG" --name "$PG" \
  --rule-name tmp-operator-bootstrap --start-ip-address "$MY_IP" --end-ip-address "$MY_IP"
```

### 3.2 Connect with an Entra token (no password)

```bash
export PGHOST=$PG.postgres.database.azure.com PGUSER=formapp-db-admins PGSSLMODE=require
export PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)
psql -d postgres
```

### 3.3 Create the principals, the database and the migration role

In the `postgres` database:

```sql
-- Entra principals for both managed identities (names = identity names).
SELECT * FROM pgaadauth_create_principal('id-sample-demo-sea-api', false, false);
SELECT * FROM pgaadauth_create_principal('id-sample-demo-sea-deploy', false, false);

-- Migration role (AD-17): owns the tables. NOLOGIN: it is only
-- ever used through SET ROLE by the pipeline identity.
CREATE ROLE formapp_migrator NOLOGIN;
-- No BYPASSRLS: with Entra-only auth, the admin (azure_pg_admin) can't grant it. Each table under row-level security
-- gets a permissive policy TO formapp_migrator in the migration that enables it (AD-17).
-- PostgreSQL 16+: the creator gets ADMIN but not SET on the new role, and the OWNER / FOR ROLE
-- statements below need SET. This grant is for this admin session's user only (formapp-db-admins).
GRANT formapp_migrator TO CURRENT_USER WITH SET TRUE;
GRANT formapp_migrator TO "id-sample-demo-sea-deploy" WITH INHERIT FALSE, SET TRUE;  -- sees every row only after SET ROLE (AD-17)

-- Application database, owned by the migration role.
CREATE DATABASE formapp OWNER formapp_migrator;
GRANT CONNECT ON DATABASE formapp TO "id-sample-demo-sea-api";
```

Then in the `formapp` database (`\c formapp`):

```sql
ALTER SCHEMA public OWNER TO formapp_migrator;
GRANT USAGE ON SCHEMA public TO "id-sample-demo-sea-api";
-- Tables and sequences the migrations create are usable by api, but api never owns them.
ALTER DEFAULT PRIVILEGES FOR ROLE formapp_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "id-sample-demo-sea-api";
ALTER DEFAULT PRIVILEGES FOR ROLE formapp_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO "id-sample-demo-sea-api";
```

The `api` identity is never granted `formapp_migrator`. The role deliberately has no `BYPASSRLS`: with Entra-only authentication the server's admin can't grant it ("permission denied to create role"), so AD-17 gives the role its own permissive policy on each table instead. If the admin can't create even this plain `NOLOGIN` role, stop and raise it.

Story 4.3 Part B: migration 0009's row-level security policies on `proposal` are granted `TO "id-sample-demo-sea-api"` -- the same identity created above, named again in the deploy workflow's migration step as `DB_API_PRINCIPAL` (`.github/workflows/deploy.yml`), read by `migrations/session.py`'s `api_principal()` the same way `DB_MIGRATION_ROLE` already is. No new bootstrap step: the identity and its table grants above already exist.

### 3.4 Delete the temporary firewall rule

Always, even if a step above failed:

```bash
az postgres flexible-server firewall-rule delete --resource-group "$RG" --name "$PG" \
  --rule-name tmp-operator-bootstrap --yes
```

### 3.5 Check

Once `api` is deployed (Story 1.3), its Entra-token connection succeeds (`/readyz`). To check the role boundary by hand, from a session signed in as the `api` identity:

```sql
SET ROLE formapp_migrator;   -- must fail: permission denied to set role
```

## Destroy order

Only the owner decides to destroy (azure.md rule 21), and only through **Actions → Destroy demo** on `main` (never locally): first with mode `plan` to read the destroy plans, then with mode `destroy`, typing `rg-sample-demo-sea`. It destroys `infra/demo/agent`, then `infra/demo/foundation`, and keeps the state storage, the deployment identity and `formapp-db-admins`. Cancel any queued Deploy demo run first: it would start right after the destroy and fail. Deleting the resource group also deletes anything in it that Terraform doesn't manage.

Destroying `foundation` deletes `rg-sample-demo-sea`, and with it the deployment identity's three resource-group roles (Contributor, the conditioned RBAC Administrator and Foundry User). Before the next pipeline run, the owner must rerun `infra/bootstrap/state-backend.sh`, which recreates the resource group and those roles. Once `api/alembic.ini` exists, the next Deploy demo fails at the migration step (the new database has no principals yet): repeat step 3, then run Deploy demo again.

## Rotating the turn-token signing key

1. Change `turn_token_signing_key_rotation` in `infra/demo/foundation/terraform.tfvars` in a pull request, and let the pipeline apply it after approval.
2. Updating a Container Apps secret does not restart the app, so the old key stays live until you restart the active revision:

```bash
REV=$(az containerapp revision list --resource-group rg-sample-demo-sea --name ca-sample-demo-sea \
  --query "[?properties.active].name | [0]" -o tsv)
az containerapp revision restart --resource-group rg-sample-demo-sea --name ca-sample-demo-sea --revision "$REV"
```

All live turn tokens become invalid, which is acceptable (10-minute lifetime, security.md rule 12).
