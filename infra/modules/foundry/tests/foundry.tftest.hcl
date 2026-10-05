# Plan-only tests with mock providers: no Azure access, no state. Run: terraform test

mock_provider "azurerm" {}
mock_provider "azapi" {}

variables {
  account_name          = "aif-sample-demo-sea"
  project_name          = "proj-sample-demo-sea"
  resource_group_name   = "rg-sample-demo-sea"
  location              = "southeastasia"
  sku_name              = "S0"
  capability_host_name  = "agents"
  model_deployment_name = "gpt-4.1-mini"
  model_format          = "OpenAI"
  model_name            = "gpt-4.1-mini"
  model_version         = "2025-04-14"
  model_sku_name        = "GlobalStandard"
  model_capacity        = 30
  tags = {
    workload  = "sample"
    env       = "demo"
    owner     = "poc-owner"
    managedby = "terraform"
    datatype  = "synthetic"
    repo      = "https://github.com/example-org/formapp"
  }
}

# A valid account ID, so the capability host's parent_id can plan.
override_resource {
  target          = azurerm_cognitive_account.this
  override_during = plan
  values = {
    id                    = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/aif-sample-demo-sea"
    custom_subdomain_name = "aif-sample-demo-sea"
  }
}

run "story_4_1_account_is_aiservices_with_keys_off" {
  command = plan

  assert {
    condition = (
      azurerm_cognitive_account.this.kind == "AIServices"
      && azurerm_cognitive_account.this.sku_name == "S0"
      && azurerm_cognitive_account.this.custom_subdomain_name == "aif-sample-demo-sea"
      && azurerm_cognitive_account.this.name == "aif-sample-demo-sea"
    )
    error_message = "The account must be AIServices S0, with its name as the custom subdomain."
  }

  assert {
    condition     = azurerm_cognitive_account.this.local_auth_enabled == false
    error_message = "Local (key) auth must be off (azure.md rule 8)."
  }

  assert {
    condition     = azurerm_cognitive_account.this.project_management_enabled
    error_message = "Project management must be on, or the account can't hold a project."
  }

  assert {
    condition     = azurerm_cognitive_account.this.identity[0].type == "SystemAssigned"
    error_message = "The account must have a system identity."
  }

  assert {
    condition     = azurerm_cognitive_account.this.location == "southeastasia" && azurerm_cognitive_account_project.this.location == "southeastasia"
    error_message = "Account and project must be in the caller's region."
  }

  assert {
    condition     = azurerm_cognitive_account.this.tags == var.tags && azurerm_cognitive_account_project.this.tags == var.tags
    error_message = "Account and project must carry the caller's tags."
  }
}

run "story_4_1_project_has_a_system_identity_and_endpoint" {
  command = plan

  assert {
    condition     = azurerm_cognitive_account_project.this.name == "proj-sample-demo-sea"
    error_message = "The project name must come from the caller."
  }

  assert {
    condition     = azurerm_cognitive_account_project.this.identity[0].type == "SystemAssigned"
    error_message = "The project must have a system identity (it pulls the agent image)."
  }

  assert {
    condition     = output.project_endpoint == "https://aif-sample-demo-sea.services.ai.azure.com/api/projects/proj-sample-demo-sea"
    error_message = "The project endpoint must be https://<subdomain>.services.ai.azure.com/api/projects/<project>."
  }
}

run "story_4_1_model_deployment_is_pinned_with_the_default_filter" {
  command = plan

  assert {
    condition = (
      azurerm_cognitive_deployment.this.model[0].format == "OpenAI"
      && azurerm_cognitive_deployment.this.model[0].name == "gpt-4.1-mini"
      && azurerm_cognitive_deployment.this.model[0].version == "2025-04-14"
    )
    error_message = "The deployment must be gpt-4.1-mini 2025-04-14 (azure.md rule 24)."
  }

  assert {
    condition     = azurerm_cognitive_deployment.this.version_upgrade_option == "NoAutoUpgrade"
    error_message = "Auto-upgrade must be off (NoAutoUpgrade)."
  }

  assert {
    condition     = azurerm_cognitive_deployment.this.sku[0].name == "GlobalStandard" && azurerm_cognitive_deployment.this.sku[0].capacity == 30
    error_message = "The deployment must be GlobalStandard with the caller's capacity."
  }

  assert {
    condition     = output.model_deployment_name == "gpt-4.1-mini"
    error_message = "model_deployment_name must be the deployment's name."
  }
}

run "story_4_1_capability_host_enables_hosted_agents" {
  command = plan

  assert {
    condition     = azapi_resource.capability_host.type == "Microsoft.CognitiveServices/accounts/capabilityHosts@2026-05-01"
    error_message = "The capability host must be an account capability host."
  }

  assert {
    condition     = azapi_resource.capability_host.parent_id == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/aif-sample-demo-sea"
    error_message = "The capability host must belong to the Foundry account."
  }

  assert {
    condition = jsonencode(azapi_resource.capability_host.body) == jsonencode({
      properties = { capabilityHostKind = "Agents" }
    })
    error_message = "The capability host must be kind Agents with no other properties."
  }
}

run "story_4_1_rejects_a_fractional_capacity" {
  command = plan

  variables {
    model_capacity = 0.5
  }

  expect_failures = [var.model_capacity]
}

run "form_226_second_deployment_is_pinned_and_can_be_active" {
  command = plan

  variables {
    next_model_deployment = {
      name     = "gpt-5.4-mini"
      format   = "OpenAI"
      model    = "gpt-5.4-mini"
      version  = "2026-03-17"
      sku_name = "GlobalStandard"
      capacity = 30
    }
    active_model_deployment = "gpt-5.4-mini"
  }

  assert {
    condition = (
      azurerm_cognitive_deployment.next[0].name == "gpt-5.4-mini"
      && azurerm_cognitive_deployment.next[0].model[0].name == "gpt-5.4-mini"
      && azurerm_cognitive_deployment.next[0].model[0].version == "2026-03-17"
      && azurerm_cognitive_deployment.next[0].version_upgrade_option == "NoAutoUpgrade"
    )
    error_message = "The second deployment must be pinned with auto-upgrade off (azure.md rule 24)."
  }

  assert {
    condition     = azurerm_cognitive_deployment.this.name == "gpt-4.1-mini"
    error_message = "Adding a second deployment must leave the first one in place."
  }

  assert {
    condition     = output.model_deployment_name == "gpt-5.4-mini" && output.model_deployment_names == ["gpt-4.1-mini", "gpt-5.4-mini"]
    error_message = "The active output must follow active_model_deployment, and both deployments must be listed."
  }
}

run "form_226_without_a_second_deployment_the_first_stays_active" {
  command = plan

  assert {
    condition     = length(azurerm_cognitive_deployment.next) == 0 && output.model_deployment_name == "gpt-4.1-mini"
    error_message = "With no next_model_deployment, nothing extra is planned and the first deployment is active."
  }
}

run "form_226_rejects_an_unknown_active_deployment" {
  command = plan

  variables {
    active_model_deployment = "gpt-5.4-mini"
  }

  expect_failures = [var.active_model_deployment]
}
