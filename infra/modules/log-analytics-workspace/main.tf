# Hand-written azurerm: the latest AVM module, Azure/avm-res-operationalinsights-workspace 0.5.1,
# requires azurerm < 5.0 and cannot run with the pinned azurerm 5.7.0 (spine Stack).
# Replace with the AVM module once a release supports azurerm 5.x.
resource "azurerm_log_analytics_workspace" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_in_days
  daily_quota_gb      = var.daily_quota_gb
  tags                = var.tags
}
