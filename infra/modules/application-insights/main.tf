# Hand-written azurerm: the latest AVM module, Azure/avm-res-insights-component 0.4.0, requires
# azurerm < 5.0 and cannot run with the pinned azurerm 5.7.0 (spine Stack).
# Replace with the AVM module once a release supports azurerm 5.x.
#
# Workspace-based (azure.md rule 14): telemetry is stored in the one Log Analytics workspace, under
# its daily cap and retention.
resource "azurerm_application_insights" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  workspace_id        = var.workspace_id
  application_type    = "web"
  # Entra-authenticated ingestion only (azure.md rule 8): the connection string alone can't send
  # telemetry; the sender also needs Monitoring Metrics Publisher (azurerm 5.x names this
  # local_authentication_enabled).
  local_authentication_enabled = false
  tags                         = var.tags
}
