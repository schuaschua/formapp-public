# Hand-written azurerm: the latest AVM module, Azure/avm-res-app-managedenvironment 0.5.0,
# requires azurerm ~> 4.0 and cannot run with the pinned azurerm 5.7.0 (spine Stack).
# Replace with the AVM module once a release supports azurerm 5.x.
resource "azurerm_container_app_environment" "this" {
  name                       = var.name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  logs_destination           = "log-analytics"
  log_analytics_workspace_id = var.log_analytics_workspace_id

  # Consumption only (azure.md rule 19). Azure adds this default profile to every new environment,
  # so it is declared here; without it every plan tries to remove it.
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  tags = var.tags
}
