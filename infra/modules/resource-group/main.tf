# The AVM resource group module is azapi-based, so it works with the pinned azurerm 5.x.
module "resource_group" {
  source  = "Azure/avm-res-resources-resourcegroup/azurerm"
  version = "0.4.0"

  name             = var.name
  location         = var.location
  enable_telemetry = true
  tags             = var.tags
}
