# The subscription comes from ARM_SUBSCRIPTION_ID (azure.md rule 6); it is never committed.
provider "azurerm" {
  # The bootstrap script registers the resource providers, so the pipeline identity needs no
  # subscription-scope rights (azure.md rule 31).
  resource_provider_registrations = "none"

  features {
    # Story 4.1: a destroyed Foundry account is purged, not left soft-deleted, so its name and
    # custom subdomain can be reused by the next apply.
    cognitive_account {
      purge_soft_delete_on_destroy = true
    }
  }
}

provider "azapi" {}
