# Hand-written azurerm (plus azapi for the capability host): the latest AVM module,
# Azure/avm-res-cognitiveservices-account 0.11.1, requires azurerm < 5.0 and cannot run with the
# pinned azurerm 5.7.0 (spine Stack). Replace with the AVM module once a release supports azurerm 5.x.

# The Foundry account (azure.md rules 5, 8 and 19): AIServices, custom subdomain (required for
# Entra auth and the Agent Service), keys off, a system identity, and projects enabled.
resource "azurerm_cognitive_account" "this" {
  name                       = var.account_name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  kind                       = "AIServices"
  sku_name                   = var.sku_name
  custom_subdomain_name      = var.account_name
  local_auth_enabled         = false
  project_management_enabled = true

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

# The project the hosted agent lives in. Its system identity pulls the agent image from the
# registry (AcrPull, assigned by the caller).
resource "azurerm_cognitive_account_project" "this" {
  name                 = var.project_name
  cognitive_account_id = azurerm_cognitive_account.this.id
  location             = var.location

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

# The model deployment (azure.md rules 24-25): pinned version, auto-upgrade off, and no
# rai_policy_name, so the default content filter stays attached. Created after the project:
# the account accepts one child operation at a time.
resource "azurerm_cognitive_deployment" "this" {
  name                   = var.model_deployment_name
  cognitive_account_id   = azurerm_cognitive_account.this.id
  version_upgrade_option = "NoAutoUpgrade"

  model {
    format  = var.model_format
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = var.model_sku_name
    capacity = var.model_capacity
  }

  depends_on = [azurerm_cognitive_account_project.this]
}

# azapi: azurerm has no resource for account capability hosts (terraform.md rule 12). An account-level
# Agents capability host enables Agent Service on the account; without connections, agent data stays
# on Microsoft-managed resources (Microsoft Learn, "Capability hosts", 2026-08). The service rejects
# enablePublicHostingEnvironment at 2026-05-01 ("Could not find member"), although azapi 2.12.0's
# schema lists it, so the body is only the kind. Capability hosts can't be updated in place, so they
# carry no tags (their properties.tags is an asset dictionary, not ARM tags).
resource "azapi_resource" "capability_host" {
  type      = "Microsoft.CognitiveServices/accounts/capabilityHosts@2026-05-01"
  name      = var.capability_host_name
  parent_id = azurerm_cognitive_account.this.id

  body = {
    properties = {
      capabilityHostKind = "Agents"
    }
  }

  depends_on = [azurerm_cognitive_deployment.this]
}

# The optional second deployment, for switching models without replacing the first (FORM-226).
# Same rules as the first: pinned version, auto-upgrade off, default content filter. Created after
# the capability host, since the account accepts one child operation at a time.
resource "azurerm_cognitive_deployment" "next" {
  count = var.next_model_deployment == null ? 0 : 1

  name                   = var.next_model_deployment.name
  cognitive_account_id   = azurerm_cognitive_account.this.id
  version_upgrade_option = "NoAutoUpgrade"

  model {
    format  = var.next_model_deployment.format
    name    = var.next_model_deployment.model
    version = var.next_model_deployment.version
  }

  sku {
    name     = var.next_model_deployment.sku_name
    capacity = var.next_model_deployment.capacity
  }

  depends_on = [azapi_resource.capability_host]
}
