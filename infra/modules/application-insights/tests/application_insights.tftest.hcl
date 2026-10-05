# Plan-only tests with a mock provider: no Azure access, no state. Run: terraform test

mock_provider "azurerm" {}

variables {
  name                = "appi-sample-demo-sea"
  resource_group_name = "rg-sample-demo-sea"
  location            = "southeastasia"
  workspace_id        = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.OperationalInsights/workspaces/log-sample-demo-sea"
  tags = {
    workload  = "sample"
    env       = "demo"
    owner     = "poc-owner"
    managedby = "terraform"
    datatype  = "synthetic"
    repo      = "https://github.com/example-org/formapp"
  }
}

run "story_1_5_workspace_based_web_component" {
  command = plan

  assert {
    condition     = azurerm_application_insights.this.workspace_id == var.workspace_id
    error_message = "Application Insights must be workspace-based (azure.md rule 14)."
  }

  assert {
    condition     = azurerm_application_insights.this.local_authentication_enabled == false
    error_message = "Ingestion must be Entra-authenticated only (local authentication off)."
  }

  assert {
    condition     = azurerm_application_insights.this.application_type == "web"
    error_message = "Application Insights must be a web component."
  }

  assert {
    condition     = azurerm_application_insights.this.location == "southeastasia" && azurerm_application_insights.this.name == "appi-sample-demo-sea"
    error_message = "Name and region must come from the caller."
  }

  assert {
    condition     = azurerm_application_insights.this.tags == var.tags
    error_message = "Application Insights must carry the caller's tags."
  }
}

run "story_1_5_connection_string_output_is_sensitive" {
  command = plan

  override_resource {
    target          = azurerm_application_insights.this
    override_during = plan
    values = {
      connection_string = "InstrumentationKey=00000000-5157-4a11-9000-00000000c0de"
    }
  }

  assert {
    condition     = issensitive(output.connection_string)
    error_message = "The connection string output must be sensitive; it grants ingestion."
  }
}
