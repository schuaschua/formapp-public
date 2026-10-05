# Hand-written azurerm: the latest AVM module, Azure/avm-res-containerregistry-registry 0.8.0,
# requires azurerm < 5.0 and cannot run with the pinned azurerm 5.7.0 (spine Stack).
# Replace with the AVM module once a release supports azurerm 5.x.
resource "azurerm_container_registry" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.sku
  admin_enabled       = false
  tags                = var.tags
}
