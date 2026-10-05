terraform {
  required_version = "1.16.4"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "5.7.0"
    }
    # Pinned now for the Foundry and authConfigs resources in Stories 1.5 and 1.6; the AVM resource
    # group module already uses it.
    azapi = {
      source  = "Azure/azapi"
      version = "2.12.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
  }

  # Created by infra/bootstrap/state-backend.sh. Entra auth only: the account has shared keys disabled.
  backend "azurerm" {
    storage_account_name = "stexampletfstatesea"
    container_name       = "formapp"
    key                  = "demo/foundation.tfstate"
    use_azuread_auth     = true
  }
}
