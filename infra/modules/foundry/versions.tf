terraform {
  required_version = ">= 1.9, < 2.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 5.7, < 6.0"
    }
    azapi = {
      source  = "Azure/azapi"
      version = ">= 2.12, < 3.0"
    }
  }
}
