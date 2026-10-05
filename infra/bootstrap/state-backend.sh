#!/usr/bin/env bash
# One-time, idempotent bootstrap for the formapp demo environment (azure.md rules 29 and 31).
#
# Run by an operator who holds Owner on the subscription, signed in with `az login`.
# Every item is "show || create": a second run changes nothing and prints "exists" for each item.
# One exception: when the deployment identity's conditioned RBAC Administrator assignment carries an
# older condition (e.g. before Monitoring Metrics Publisher was allowed, Story 1.5), that one
# assignment is deleted and recreated with the current condition, and the script says so.
#
# Creates:
#   - central state store shared by all apps: rg-tfstate-sea + stexampletfstatesea (shared key off, blob
#     versioning on), plus this app's own container formapp
#   - Storage Blob Data Contributor on the state container for the signed-in operator (local terraform plan)
#   - rg-sample-demo-sea with the six required tags (adopted by the foundation stack via an import block)
#   - resource provider registrations the stacks need
#   - Entra group formapp-db-admins (PostgreSQL Entra admin) with the operator as a member
#   - Entra group formapp-feedback-readers with Storage Blob Data Reader, at account scope, on the
#     feedback export's own storage account (Story 7.1/FORM-237, FORM-240, AD-20) once it exists;
#     rerun after the first foundation apply if it doesn't. Its old grant on the removed
#     stsampledemosea/feedback-export container is deleted.
#   - id-sample-demo-sea-deploy (pipeline identity) with GitHub OIDC federated credentials and exactly:
#       Contributor on rg-sample-demo-sea
#       Role Based Access Control Administrator on rg-sample-demo-sea (conditioned: AcrPull,
#         Foundry User, Monitoring Metrics Publisher, Storage Blob Data Contributor and
#         Cognitive Services Speech User only, service principals only)
#       Storage Blob Data Contributor on the state container
#       Foundry User on rg-sample-demo-sea (Story 4.1: create the hosted agent in the Foundry data
#         plane, and the deploy's smoke call to it)
#
# Usage: infra/bootstrap/state-backend.sh [subscription-id]
#   Without an argument it uses the az CLI's current subscription.

set -Eeuo pipefail

# ---------------------------------------------------------------------------
# Settings (names follow docs/standards/azure.md)
# ---------------------------------------------------------------------------
readonly LOCATION="southeastasia"
readonly STATE_RG="rg-tfstate-sea"
readonly STATE_ACCOUNT="stexampletfstatesea"
readonly STATE_CONTAINER="formapp"
readonly DEMO_RG="rg-sample-demo-sea"
readonly DEPLOY_IDENTITY="id-sample-demo-sea-deploy"
readonly DB_ADMIN_GROUP="formapp-db-admins"
# Story 7.1/FORM-237 (AD-20): Power BI leads read the feedback snapshot with this group's Storage
# Blob Data Reader on feedback-export; the container name and account name mirror
# infra/demo/foundation/locals.tf's local.feedback_export_container and local.names.storage_account.
readonly FEEDBACK_READERS_GROUP="formapp-feedback-readers"
readonly DEMO_STORAGE_ACCOUNT="stsampledemosea"
readonly FEEDBACK_EXPORT_CONTAINER="feedback-export"
# FORM-240: the feedback export's own storage account, so Power BI's per-account credential test
# never lists the sign-in token store's container; mirrors
# infra/demo/foundation/locals.tf's local.names.feedback_export_storage_account. The old
# feedback-export container on DEMO_STORAGE_ACCOUNT was removed (owner, 2026-09-28); the step
# below deletes FEEDBACK_READERS_GROUP's leftover grant on it.
readonly FEEDBACK_EXPORT_STORAGE_ACCOUNT="stsamplefbdemosea"
readonly GITHUB_REPO="example-org/formapp"
readonly GITHUB_ISSUER="https://token.actions.githubusercontent.com"
readonly GITHUB_AUDIENCE="api://AzureADTokenExchange"
readonly REPO_URL="https://github.com/${GITHUB_REPO}"

# The six required tags. The demo RG is adopted by Terraform, so it says managedby=terraform;
# the state resources and the deployment identity are managed by this script.
readonly DEMO_TAGS=(workload=sample env=demo owner=poc-owner managedby=terraform datatype=synthetic "repo=${REPO_URL}")
readonly BOOTSTRAP_TAGS=(workload=sample env=demo owner=poc-owner managedby=bootstrap datatype=synthetic "repo=${REPO_URL}")
# The central state resource group and account are shared by all apps, so they carry no app workload.
readonly SHARED_TAGS=(workload=tfstate env=shared owner=poc-owner managedby=bootstrap datatype=synthetic "repo=${REPO_URL}")

# Resource providers used by the foundation and agent stacks (the pipeline can't register them).
readonly PROVIDERS=(
  Microsoft.App
  Microsoft.ContainerRegistry
  Microsoft.OperationalInsights
  Microsoft.Insights
  Microsoft.AlertsManagement
  Microsoft.DBforPostgreSQL
  Microsoft.ManagedIdentity
  Microsoft.CognitiveServices
  Microsoft.Consumption
  Microsoft.Storage
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
CURRENT_STEP="start"

step() {
  CURRENT_STEP="$1"
  echo
  echo "==> ${CURRENT_STEP}"
}

on_error() {
  echo >&2
  echo "FAILED at step: ${CURRENT_STEP}" >&2
  echo "Nothing after this step ran. Fix the cause and rerun; completed steps are skipped." >&2
}
trap on_error ERR

die() {
  echo "ERROR: $*" >&2
  exit 1
}

exists() { echo "    exists:  $*"; }
created() { echo "    created: $*"; }
updated() { echo "    updated: $*"; }
lower() { tr '[:upper:]' '[:lower:]'; }

# Resolve a built-in role's definition GUID by its display name at run time.
role_id() {
  local id
  id="$(az role definition list --name "$1" --query "[0].name" -o tsv)"
  [[ -n "${id}" ]] || return 1
  echo "${id}"
}

# Idempotently assign a role (by GUID) to a principal at a scope.
# Args: principal_id principal_type role_guid role_label scope [condition]
ensure_role_assignment() {
  local principal_id="$1" principal_type="$2" role_guid="$3" role_label="$4" scope="$5" condition="${6:-}"
  local count attempt replacing=""
  count="$(az role assignment list --scope "${scope}" --role "${role_guid}" \
    --query "length([?principalId=='${principal_id}'])" -o tsv)"
  if [[ "${count}" != "0" ]]; then
    local current ids
    current="$(az role assignment list --scope "${scope}" --role "${role_guid}" \
      --query "[?principalId=='${principal_id}'].condition" -o tsv)"
    # tsv prints a missing condition as "None".
    if [[ -z "${condition}" || "$(lower <<<"${current}")" == "$(lower <<<"${condition}")" ]]; then
      exists "${role_label} for ${principal_id} on ${scope##*/providers/}"
      return 0
    fi
    # The condition changed (a role was added to it): replace this one assignment.
    echo "    condition differs: deleting ${role_label} for ${principal_id} on ${scope##*/providers/} to recreate it"
    ids="$(az role assignment list --scope "${scope}" --role "${role_guid}" \
      --query "[?principalId=='${principal_id}'].id" -o tsv)"
    local id
    while IFS= read -r id; do
      [[ -n "${id}" ]] || continue
      az role assignment delete --ids "${id}" --output none
      echo "    deleted: ${id}"
    done <<<"${ids}"
    replacing=1
  fi

  local args=(--assignee-object-id "${principal_id}" --assignee-principal-type "${principal_type}"
    --role "${role_guid}" --scope "${scope}" --output none)
  if [[ -n "${condition}" ]]; then
    args+=(--condition "${condition}" --condition-version "2.0")
  fi

  # A freshly created identity can take a moment to replicate in Entra ID.
  for attempt in 1 2 3 4 5 6; do
    if az role assignment create "${args[@]}"; then
      if [[ -n "${replacing}" ]]; then
        updated "${role_label} for ${principal_id} on ${scope##*/providers/} (new condition)"
      else
        created "${role_label} for ${principal_id} on ${scope##*/providers/}"
      fi
      return 0
    fi
    echo "    retrying role assignment in 10s (attempt ${attempt}/6)"
    sleep 10
  done
  return 1
}

# ---------------------------------------------------------------------------
# Preconditions: signed in, right subscription, Owner. Nothing is created before these pass.
# ---------------------------------------------------------------------------
step "Check az CLI sign-in"
command -v az >/dev/null 2>&1 || die "az CLI not found. Install it and run 'az login'."
az account show --output none 2>/dev/null || die "Not signed in. Run 'az login' as a subscription Owner, then rerun."

if [[ $# -ge 1 ]]; then
  az account set --subscription "$1" || die "Cannot select subscription '$1'."
fi
SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"
SUBSCRIPTION_SCOPE="/subscriptions/${SUBSCRIPTION_ID}"
echo "    subscription: $(az account show --query name -o tsv) (${SUBSCRIPTION_ID})"

step "Read the GitHub OIDC subject prefix for ${GITHUB_REPO}"
# Repos created or transferred after 2026-07-15 use GitHub's immutable subject (owner and repo IDs),
# so the prefix is read from GitHub, never built from the repo name (spine AD-11).
command -v gh >/dev/null 2>&1 || die "gh CLI not found. Install it and run 'gh auth login'."
OIDC_SUB_PREFIX="$(gh api "repos/${GITHUB_REPO}/actions/oidc/customization/sub" --jq '.sub_claim_prefix // empty' 2>/dev/null)" \
  || die "Cannot read the OIDC subject settings of ${GITHUB_REPO}. Run 'gh auth login' with access to the repo."
[[ -n "${OIDC_SUB_PREFIX}" ]] || OIDC_SUB_PREFIX="repo:${GITHUB_REPO}"
echo "    subject prefix: ${OIDC_SUB_PREFIX}"

OPERATOR_ID="$(az ad signed-in-user show --query id -o tsv 2>/dev/null)" \
  || die "Sign in as a user ('az login'), not a service principal: the operator is added to ${DB_ADMIN_GROUP}."
echo "    operator:     $(az ad signed-in-user show --query userPrincipalName -o tsv) (${OPERATOR_ID})"

step "Check the operator holds Owner on the subscription"
OWNER_COUNT="$(az role assignment list --assignee "${OPERATOR_ID}" --scope "${SUBSCRIPTION_SCOPE}" \
  --include-inherited --include-groups --role Owner --query "length(@)" -o tsv)"
[[ "${OWNER_COUNT}" != "0" ]] || die "The signed-in user is not Owner on subscription ${SUBSCRIPTION_ID}. Nothing was created."

step "Resolve role definition IDs by name"
ROLE_CONTRIBUTOR="$(role_id "Contributor")" || die "Role 'Contributor' not found."
ROLE_RBAC_ADMIN="$(role_id "Role Based Access Control Administrator")" || die "Role 'Role Based Access Control Administrator' not found."
ROLE_BLOB_CONTRIBUTOR="$(role_id "Storage Blob Data Contributor")" || die "Role 'Storage Blob Data Contributor' not found."
ROLE_ACR_PULL="$(role_id "AcrPull")" || die "Role 'AcrPull' not found."
# Foundry User was formerly named Azure AI User; accept either display name.
ROLE_FOUNDRY_USER="$(role_id "Foundry User" || role_id "Azure AI User")" || die "Role 'Foundry User' (Azure AI User) not found."
# Story 1.5: api publishes telemetry to Application Insights with its managed identity.
ROLE_MONITORING_PUBLISHER="$(role_id "Monitoring Metrics Publisher")" || die "Role 'Monitoring Metrics Publisher' not found."
# Story 6.1 (AD-19): foundation gives the dedicated speech identity this role on the Speech account.
ROLE_SPEECH_USER="$(role_id "Cognitive Services Speech User")" || die "Role 'Cognitive Services Speech User' not found."
# Story 7.1/FORM-237 (AD-20): this script (never the deploy identity) assigns this role directly to
# formapp-feedback-readers, a Group principal -- the deploy identity's RBAC Administrator condition
# may assign its roles only to service principals, so Reader never needs to join that condition.
ROLE_BLOB_READER="$(role_id "Storage Blob Data Reader")" || die "Role 'Storage Blob Data Reader' not found."
echo "    Contributor=${ROLE_CONTRIBUTOR} RBAC Administrator=${ROLE_RBAC_ADMIN}"
echo "    Storage Blob Data Contributor=${ROLE_BLOB_CONTRIBUTOR} AcrPull=${ROLE_ACR_PULL} Foundry User=${ROLE_FOUNDRY_USER}"
echo "    Monitoring Metrics Publisher=${ROLE_MONITORING_PUBLISHER} Cognitive Services Speech User=${ROLE_SPEECH_USER}"
# The verify step compares display names; use whichever name this tenant shows for Foundry User.
ROLE_FOUNDRY_USER_NAME="$(az role definition list --name "${ROLE_FOUNDRY_USER}" --query "[0].roleName" -o tsv)"
[[ -n "${ROLE_FOUNDRY_USER_NAME}" ]] || die "Cannot read the display name of role ${ROLE_FOUNDRY_USER}."

# ---------------------------------------------------------------------------
# Terraform state storage
# ---------------------------------------------------------------------------
step "State resource group ${STATE_RG}"
if az group show --name "${STATE_RG}" --output none 2>/dev/null; then
  exists "${STATE_RG}"
else
  az group create --name "${STATE_RG}" --location "${LOCATION}" --tags "${SHARED_TAGS[@]}" --output none
  created "${STATE_RG}"
fi

step "State storage account ${STATE_ACCOUNT}"
if az storage account show --resource-group "${STATE_RG}" --name "${STATE_ACCOUNT}" --output none 2>/dev/null; then
  exists "${STATE_ACCOUNT}"
else
  az storage account create \
    --resource-group "${STATE_RG}" --name "${STATE_ACCOUNT}" --location "${LOCATION}" \
    --kind StorageV2 --sku Standard_LRS --https-only true --min-tls-version TLS1_2 \
    --allow-blob-public-access false --allow-shared-key-access false \
    --tags "${SHARED_TAGS[@]}" --output none
  created "${STATE_ACCOUNT}"
fi
STATE_ACCOUNT_ID="$(az storage account show --resource-group "${STATE_RG}" --name "${STATE_ACCOUNT}" --query id -o tsv)"

step "Blob versioning on ${STATE_ACCOUNT}"
VERSIONING="$(az storage account blob-service-properties show --resource-group "${STATE_RG}" \
  --account-name "${STATE_ACCOUNT}" --query "isVersioningEnabled" -o tsv)"
if [[ "${VERSIONING}" == "true" ]]; then
  exists "blob versioning"
else
  az storage account blob-service-properties update --resource-group "${STATE_RG}" \
    --account-name "${STATE_ACCOUNT}" --enable-versioning true --output none
  created "blob versioning"
fi

step "State container ${STATE_CONTAINER}"
# Management-plane (container-rm) calls: shared keys are off and Owner has no data-plane rights.
if [[ "$(az storage container-rm exists --resource-group "${STATE_RG}" --storage-account "${STATE_ACCOUNT}" \
  --name "${STATE_CONTAINER}" --query exists -o tsv)" == "true" ]]; then
  exists "${STATE_CONTAINER}"
else
  az storage container-rm create --resource-group "${STATE_RG}" --storage-account "${STATE_ACCOUNT}" \
    --name "${STATE_CONTAINER}" --public-access off --output none
  created "${STATE_CONTAINER}"
fi
STATE_CONTAINER_SCOPE="${STATE_ACCOUNT_ID}/blobServices/default/containers/${STATE_CONTAINER}"

step "Operator access to the state container (local terraform plan)"
ensure_role_assignment "${OPERATOR_ID}" User "${ROLE_BLOB_CONTRIBUTOR}" "Storage Blob Data Contributor" \
  "${STATE_CONTAINER_SCOPE}"

# ---------------------------------------------------------------------------
# Demo resource group (adopted by the foundation stack)
# ---------------------------------------------------------------------------
step "Demo resource group ${DEMO_RG}"
if az group show --name "${DEMO_RG}" --output none 2>/dev/null; then
  exists "${DEMO_RG}"
else
  az group create --name "${DEMO_RG}" --location "${LOCATION}" --tags "${DEMO_TAGS[@]}" --output none
  created "${DEMO_RG}"
fi
DEMO_RG_ID="$(az group show --name "${DEMO_RG}" --query id -o tsv)"

# ---------------------------------------------------------------------------
# Resource provider registrations
# ---------------------------------------------------------------------------
step "Resource provider registrations"
for provider in "${PROVIDERS[@]}"; do
  state="$(az provider show --namespace "${provider}" --query registrationState -o tsv 2>/dev/null || echo "NotRegistered")"
  if [[ "${state}" == "Registered" ]]; then
    exists "${provider}"
  else
    az provider register --namespace "${provider}" --wait --output none
    created "${provider} registration"
  fi
done

# ---------------------------------------------------------------------------
# PostgreSQL Entra admin group
# ---------------------------------------------------------------------------
step "Entra group ${DB_ADMIN_GROUP}"
# Exact match (--display-name is a prefix match).
DB_ADMIN_GROUP_ID="$(az ad group list --filter "displayName eq '${DB_ADMIN_GROUP}'" --query "[].id" -o tsv)"
if [[ "$(printf '%s\n' "${DB_ADMIN_GROUP_ID}" | grep -c . || true)" -gt 1 ]]; then
  die "More than one Entra group is named ${DB_ADMIN_GROUP}; delete or rename the extras and rerun."
fi
if [[ -n "${DB_ADMIN_GROUP_ID}" ]]; then
  exists "${DB_ADMIN_GROUP}"
else
  DB_ADMIN_GROUP_ID="$(az ad group create --display-name "${DB_ADMIN_GROUP}" --mail-nickname "${DB_ADMIN_GROUP}" \
    --description "PostgreSQL Entra administrators for formapp demo" --query id -o tsv)"
  created "${DB_ADMIN_GROUP}"
fi

step "Operator membership of ${DB_ADMIN_GROUP}"
if [[ "$(az ad group member check --group "${DB_ADMIN_GROUP_ID}" --member-id "${OPERATOR_ID}" --query value -o tsv)" == "true" ]]; then
  exists "operator in ${DB_ADMIN_GROUP}"
else
  az ad group member add --group "${DB_ADMIN_GROUP_ID}" --member-id "${OPERATOR_ID}"
  created "operator in ${DB_ADMIN_GROUP}"
fi

# ---------------------------------------------------------------------------
# Nightly feedback job readers (Story 7.1/FORM-237, spine AD-20)
# ---------------------------------------------------------------------------
step "Entra group ${FEEDBACK_READERS_GROUP}"
# Exact match (--display-name is a prefix match).
FEEDBACK_READERS_GROUP_ID="$(az ad group list --filter "displayName eq '${FEEDBACK_READERS_GROUP}'" --query "[].id" -o tsv)"
if [[ "$(printf '%s\n' "${FEEDBACK_READERS_GROUP_ID}" | grep -c . || true)" -gt 1 ]]; then
  die "More than one Entra group is named ${FEEDBACK_READERS_GROUP}; delete or rename the extras and rerun."
fi
if [[ -n "${FEEDBACK_READERS_GROUP_ID}" ]]; then
  exists "${FEEDBACK_READERS_GROUP}"
else
  FEEDBACK_READERS_GROUP_ID="$(az ad group create --display-name "${FEEDBACK_READERS_GROUP}" \
    --mail-nickname "${FEEDBACK_READERS_GROUP}" \
    --description "Power BI readers of the formapp demo feedback-export snapshot" --query id -o tsv)"
  created "${FEEDBACK_READERS_GROUP}"
fi

step "Remove ${FEEDBACK_READERS_GROUP}'s old grant on ${DEMO_STORAGE_ACCOUNT}/${FEEDBACK_EXPORT_CONTAINER}"
# FORM-240 clean-up: the export moved to its own account and Terraform removed the old container, so
# the group's container-scoped Reader there is a leftover. Matched by scope text, because the
# container itself may already be gone.
OLD_FEEDBACK_GRANTS="$(az role assignment list --assignee "${FEEDBACK_READERS_GROUP_ID}" --all \
  --query "[?ends_with(scope, '/storageAccounts/${DEMO_STORAGE_ACCOUNT}/blobServices/default/containers/${FEEDBACK_EXPORT_CONTAINER}')].id" -o tsv)"
if [[ -z "${OLD_FEEDBACK_GRANTS}" ]]; then
  echo "    exists:  nothing to remove"
else
  # shellcheck disable=SC2086 # one id per line, split on purpose
  az role assignment delete --ids ${OLD_FEEDBACK_GRANTS} --output none
  echo "    deleted: Storage Blob Data Reader for ${FEEDBACK_READERS_GROUP} on ${DEMO_STORAGE_ACCOUNT}/${FEEDBACK_EXPORT_CONTAINER}"
fi

step "${FEEDBACK_READERS_GROUP} access to ${FEEDBACK_EXPORT_STORAGE_ACCOUNT} (FORM-240)"
# Account-level, not container-level: Power BI records a Blob source by storage account and, when
# saving credentials, test-lists every container in it -- a container-scoped grant made that test
# fail once this account existed alongside a token store on the same account, so FORM-240 gave the
# export its own account and this grant is account-scope. Harmless here: this account holds only
# feedback-export. Same tolerance as the step above -- this stack's Terraform creates the account.
if ! az storage account show --resource-group "${DEMO_RG}" --name "${FEEDBACK_EXPORT_STORAGE_ACCOUNT}" --output none 2>/dev/null; then
  echo "    note: storage account ${FEEDBACK_EXPORT_STORAGE_ACCOUNT} does not exist yet; rerun this script after the first foundation apply that includes FORM-240."
else
  FEEDBACK_EXPORT_ACCOUNT_ID="$(az storage account show --resource-group "${DEMO_RG}" --name "${FEEDBACK_EXPORT_STORAGE_ACCOUNT}" --query id -o tsv)"
  ensure_role_assignment "${FEEDBACK_READERS_GROUP_ID}" Group "${ROLE_BLOB_READER}" "Storage Blob Data Reader" \
    "${FEEDBACK_EXPORT_ACCOUNT_ID}"
fi

# ---------------------------------------------------------------------------
# Pipeline deployment identity
# ---------------------------------------------------------------------------
step "Deployment identity ${DEPLOY_IDENTITY}"
if az identity show --resource-group "${STATE_RG}" --name "${DEPLOY_IDENTITY}" --output none 2>/dev/null; then
  exists "${DEPLOY_IDENTITY}"
else
  az identity create --resource-group "${STATE_RG}" --name "${DEPLOY_IDENTITY}" --location "${LOCATION}" \
    --tags "${BOOTSTRAP_TAGS[@]}" --output none
  created "${DEPLOY_IDENTITY}"
fi
DEPLOY_PRINCIPAL_ID="$(az identity show --resource-group "${STATE_RG}" --name "${DEPLOY_IDENTITY}" --query principalId -o tsv)"
DEPLOY_CLIENT_ID="$(az identity show --resource-group "${STATE_RG}" --name "${DEPLOY_IDENTITY}" --query clientId -o tsv)"

step "Federated credentials for ${GITHUB_REPO}"
ensure_federated_credential() {
  local name="$1" subject="$2" current
  # '|| true' inside the substitution: a missing credential is expected, and must not trip the ERR trap.
  current="$(az identity federated-credential show --resource-group "${STATE_RG}" --identity-name "${DEPLOY_IDENTITY}" \
    --name "${name}" --query subject -o tsv 2>/dev/null || true)"
  if [[ -n "${current}" ]]; then
    # A credential with the right name but another subject would never match GitHub's token.
    [[ "${current}" == "${subject}" ]] || die "Federated credential ${name} trusts '${current}', expected '${subject}'. Delete it (az identity federated-credential delete -g ${STATE_RG} --identity-name ${DEPLOY_IDENTITY} -n ${name} --yes) and rerun."
    exists "federated credential ${name} (${subject})"
  else
    az identity federated-credential create --resource-group "${STATE_RG}" --identity-name "${DEPLOY_IDENTITY}" \
      --name "${name}" --issuer "${GITHUB_ISSUER}" --subject "${subject}" --audiences "${GITHUB_AUDIENCE}" \
      --output none
    created "federated credential ${name} (${subject})"
  fi
}
ensure_federated_credential "github-pull-request" "${OIDC_SUB_PREFIX}:pull_request"
ensure_federated_credential "github-environment-demo" "${OIDC_SUB_PREFIX}:environment:demo"

step "Deployment identity role assignments"
# RBAC Administrator may write or delete only AcrPull, Foundry User, Monitoring Metrics Publisher,
# Storage Blob Data Contributor and Cognitive Services Speech User assignments, and only for service
# principals (azure.md rule 31).
# Story 1.6: Storage Blob Data Contributor lets foundation give the api identity the sign-in token
# store container.
ALLOWED_ROLES="${ROLE_ACR_PULL}, ${ROLE_FOUNDRY_USER}, ${ROLE_MONITORING_PUBLISHER}, ${ROLE_BLOB_CONTRIBUTOR}, ${ROLE_SPEECH_USER}"
RBAC_CONDITION="((!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${ALLOWED_ROLES}} AND @Request[Microsoft.Authorization/roleAssignments:PrincipalType] StringEqualsIgnoreCase 'ServicePrincipal')) AND ((!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'})) OR (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${ALLOWED_ROLES}} AND @Resource[Microsoft.Authorization/roleAssignments:PrincipalType] StringEqualsIgnoreCase 'ServicePrincipal'))"

ensure_role_assignment "${DEPLOY_PRINCIPAL_ID}" ServicePrincipal "${ROLE_CONTRIBUTOR}" "Contributor" "${DEMO_RG_ID}"
ensure_role_assignment "${DEPLOY_PRINCIPAL_ID}" ServicePrincipal "${ROLE_RBAC_ADMIN}" \
  "Role Based Access Control Administrator (conditioned)" "${DEMO_RG_ID}" "${RBAC_CONDITION}"
ensure_role_assignment "${DEPLOY_PRINCIPAL_ID}" ServicePrincipal "${ROLE_BLOB_CONTRIBUTOR}" \
  "Storage Blob Data Contributor" "${STATE_CONTAINER_SCOPE}"
# Story 4.1 (owner, 2026-09-26): Foundry data-plane rights. Contributor has none, and the agent stack
# creates the hosted agent through the data plane; the deploy's smoke check calls it.
ensure_role_assignment "${DEPLOY_PRINCIPAL_ID}" ServicePrincipal "${ROLE_FOUNDRY_USER}" "${ROLE_FOUNDRY_USER_NAME}" "${DEMO_RG_ID}"

step "Verify the deployment identity holds exactly its 4 role assignments"
# Compare role, scope and condition of every assignment with the expected set (case-insensitive;
# tsv prints a missing condition as "None").
ACTUAL_ASSIGNMENTS="$(az role assignment list --all \
  --query "[?principalId=='${DEPLOY_PRINCIPAL_ID}'].[roleDefinitionName, scope, condition]" -o tsv | lower | sort)"
EXPECTED_ASSIGNMENTS="$(printf '%s\t%s\t%s\n' \
  "Contributor" "${DEMO_RG_ID}" "None" \
  "Role Based Access Control Administrator" "${DEMO_RG_ID}" "${RBAC_CONDITION}" \
  "Storage Blob Data Contributor" "${STATE_CONTAINER_SCOPE}" "None" \
  "${ROLE_FOUNDRY_USER_NAME}" "${DEMO_RG_ID}" "None" | lower | sort)"
if [[ "${ACTUAL_ASSIGNMENTS}" != "${EXPECTED_ASSIGNMENTS}" ]]; then
  echo "Expected (role, scope, condition):" >&2
  printf '%s\n' "${EXPECTED_ASSIGNMENTS}" >&2
  echo "Actual:" >&2
  printf '%s\n' "${ACTUAL_ASSIGNMENTS}" >&2
  die "${DEPLOY_IDENTITY} role assignments differ from the expected four (missing, extra, or wrong condition). Fix them by hand and rerun."
fi
echo "    ok: exactly Contributor, conditioned RBAC Administrator, Storage Blob Data Contributor and ${ROLE_FOUNDRY_USER_NAME}"

# ---------------------------------------------------------------------------
# Values for the next steps (none of these are secrets)
# ---------------------------------------------------------------------------
step "Done"
cat <<EOF
    GitHub repository variables (Story 1.2):
      AZURE_TENANT_ID=${TENANT_ID}
      AZURE_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}
      AZURE_CLIENT_ID=${DEPLOY_CLIENT_ID}
    infra/demo/foundation/terraform.tfvars:
      db_admin_group_object_id = "${DB_ADMIN_GROUP_ID}"
    Local plan:
      export ARM_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}
EOF
