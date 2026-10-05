# The AVM storage account module is azapi-based, so it works with the pinned azurerm 5.x.
#
# Story 1.6: the Container Apps sign-in token store. Entra only: shared keys (and so SAS) off, no
# anonymous blob access, TLS 1.2, the cheapest tier (Standard LRS, azure.md rule 19). Public network
# access stays on with an Allow default, like every other endpoint in the POC (azure.md rule 11):
# Consumption Container Apps have no fixed outbound address to allow instead.
locals {
  # Private containers only; their role assignments are declared by the caller, at container scope.
  containers = {
    for name in var.container_names : name => {
      name          = name
      public_access = "None"
    }
  }
}

module "storage_account" {
  source  = "Azure/avm-res-storage-storageaccount/azurerm"
  version = "0.10.0"

  name      = var.name
  location  = var.location
  parent_id = var.resource_group_id

  account_kind                    = "StorageV2"
  account_sku_name                = "Standard_LRS"
  access_tier                     = "Hot"
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  public_network_access_enabled   = true
  network_rules = {
    default_action = "Allow"
    bypass         = ["AzureServices"]
  }

  containers = local.containers

  enable_telemetry = true
  tags             = var.tags
}
