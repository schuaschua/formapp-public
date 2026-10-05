terraform {
  required_version = "1.16.4"

  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = "2.12.0"
    }
  }

  # Created by infra/bootstrap/state-backend.sh. Entra auth only: the account has shared keys disabled.
  backend "azurerm" {
    storage_account_name = "stexampletfstatesea"
    container_name       = "formapp"
    key                  = "demo/agent.tfstate"
    use_azuread_auth     = true
  }
}
