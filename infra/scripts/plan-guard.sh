#!/usr/bin/env bash
# Deploy guard (AD-11, terraform.md rule 33): fails when a Terraform plan would destroy or replace a
# protected resource: the resource group, PostgreSQL (server or database), the Container Apps
# environment, or any Foundry resource, whether written with azurerm or azapi.
#
# Usage: infra/scripts/plan-guard.sh <plan.json>   (from `terraform show -json tfplan`)
# Exit:  0 nothing protected is destroyed or replaced; 1 blocked (each address printed); 2 bad input.

set -Eeuo pipefail

if [[ $# -ne 1 || ! -r "$1" ]]; then
  echo "Usage: $0 <plan.json>" >&2
  exit 2
fi

# azurerm resource types, matched exactly or by prefix (Foundry).
# azapi resources are matched by their ARM type (before or after), case-insensitively.
readonly FILTER='
  (.resource_changes // [])[]
  | select(.change.actions | index("delete"))
  | select(
      (.type | IN(
        "azurerm_resource_group",
        "azurerm_postgresql_flexible_server",
        "azurerm_postgresql_flexible_server_database",
        "azurerm_container_app_environment"))
      or (.type | test("^azurerm_(cognitive_|ai_foundry|ai_services)"))
      or ((.type | startswith("azapi_"))
          and (((.change.before.type // "") + " " + (.change.after.type // ""))
               | test("(^| )(Microsoft\\.Resources/resourceGroups|Microsoft\\.DBforPostgreSQL/flexibleServers|Microsoft\\.App/managedEnvironments|Microsoft\\.CognitiveServices/|Microsoft\\.MachineLearningServices/)"; "i")))
    )
  | "\(.address) (\(.change.actions | join(", ")))"
'

if ! blocked="$(jq -r "$FILTER" "$1")"; then
  echo "Cannot read the plan JSON in $1." >&2
  exit 2
fi

if [[ -n "$blocked" ]]; then
  while IFS= read -r line; do
    echo "::error::The plan would destroy or replace a protected resource: ${line}"
  done <<<"$blocked"
  echo "Nothing was applied. Change the code so the plan keeps these resources; only the owner destroys the environment (azure.md rule 21)."
  exit 1
fi

echo "No protected resource is destroyed or replaced."
