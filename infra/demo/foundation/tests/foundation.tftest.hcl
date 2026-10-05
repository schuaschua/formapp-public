# Plan-only tests with mock providers: no Azure access, no state. Run: terraform test

mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-00000000000a"
      subscription_id = "00000000-0000-0000-0000-00000000000b"
    }
  }
}

mock_provider "azapi" {}
mock_provider "random" {}

# Mock providers can't import, so the resource group adopted by the import block is overridden.
override_resource {
  target = module.resource_group.module.resource_group.azapi_resource.this
  values = {
    id     = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea"
    body   = { properties = {} }
    output = {}
  }
}

# The AVM telemetry header (random_uuid) must be known during plan, or the mocked import's
# refresh sees unknown request headers.
override_resource {
  target          = module.resource_group.module.resource_group.random_uuid.telemetry
  override_during = plan
  values = {
    result = "00000000-0000-4000-8000-000000000000"
  }
}

# Known values for the api container's settings (DATABASE_HOST, AZURE_CLIENT_ID), so plan-only runs
# can check the container spec and the api_container output.
override_resource {
  target          = module.api_identity.azurerm_user_assigned_identity.this
  override_during = plan
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-sample-demo-sea-api"
    client_id    = "00000000-0000-0000-0000-0000000000c1"
    principal_id = "00000000-0000-0000-0000-0000000000d1"
  }
}

override_resource {
  target          = module.postgresql_flexible_server.azurerm_postgresql_flexible_server.this
  override_during = plan
  values = {
    id   = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.DBforPostgreSQL/flexibleServers/pgsql-sample-demo-sea"
    fqdn = "pgsql-sample-demo-sea.postgres.database.azure.com"
  }
}

# A valid resource ID, so the api identity's role assignment on Application Insights can plan.
override_resource {
  target          = module.application_insights.azurerm_application_insights.this
  override_during = plan
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/components/appi-sample-demo-sea"
  }
}

# Story 1.6: known IDs for the token-store account and container, so the container and its role
# assignment plan with valid resource IDs.
override_resource {
  target          = module.token_store.module.storage_account.azapi_resource.this
  override_during = plan
  values = {
    id   = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Storage/storageAccounts/stsampledemosea"
    name = "stsampledemosea"
  }
}

override_resource {
  target          = module.token_store.module.storage_account.module.containers["tokenstore"].azapi_resource.this
  override_during = plan
  values = {
    id   = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Storage/storageAccounts/stsampledemosea/blobServices/default/containers/tokenstore"
    name = "tokenstore"
  }
}

override_resource {
  target          = azurerm_container_app.api
  override_during = plan
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.App/containerApps/ca-sample-demo-sea"
  }
}

# Story 4.1: valid Foundry and registry IDs and a known project identity, so the Foundry role
# assignments, connection and diagnostic setting can plan.
override_resource {
  target          = module.foundry.azurerm_cognitive_account.this
  override_during = plan
  values = {
    id                    = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/aif-sample-demo-sea"
    custom_subdomain_name = "aif-sample-demo-sea"
  }
}

override_resource {
  target          = module.foundry.azurerm_cognitive_account_project.this
  override_during = plan
  values = {
    id       = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/aif-sample-demo-sea/projects/proj-sample-demo-sea"
    identity = { principal_id = "00000000-0000-0000-0000-0000000000e1" }
  }
}

override_resource {
  target          = module.container_registry.azurerm_container_registry.this
  override_during = plan
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.ContainerRegistry/registries/crsampledemosea"
  }
}

# terraform.tfvars is loaded; this replaces its all-zero placeholder with a valid GUID.
variables {
  db_admin_group_object_id = "11111111-2222-3333-4444-555555555555"
}

run "acr_pull_is_service_principal_scoped" {
  command = plan

  assert {
    condition     = azurerm_role_assignment.api_acr_pull.role_definition_name == "AcrPull"
    error_message = "The api identity must get AcrPull."
  }

  assert {
    condition     = azurerm_role_assignment.api_acr_pull.principal_type == "ServicePrincipal"
    error_message = "principal_type must be ServicePrincipal (the pipeline's RBAC Administrator condition requires it)."
  }
}

run "naming_contract" {
  command = plan

  assert {
    condition     = local.names.resource_group == "rg-sample-demo-sea"
    error_message = "Resource group name must be rg-sample-demo-sea."
  }

  assert {
    condition     = local.names.container_registry == "crsampledemosea"
    error_message = "Registry name must be crsampledemosea."
  }
}

run "six_required_tags" {
  command = plan

  assert {
    condition     = toset(keys(local.tags)) == toset(["workload", "env", "owner", "managedby", "datatype", "repo"])
    error_message = "local.tags must have exactly the six required keys."
  }

  assert {
    condition     = local.tags.managedby == "terraform"
    error_message = "managedby must be terraform."
  }
}

run "rejects_all_zero_db_admin_group_id" {
  command = plan

  variables {
    db_admin_group_object_id = "00000000-0000-0000-0000-000000000000"
  }

  expect_failures = [var.db_admin_group_object_id]
}

run "rejects_non_guid_db_admin_group_id" {
  command = plan

  variables {
    db_admin_group_object_id = "formapp-db-admins"
  }

  expect_failures = [var.db_admin_group_object_id]
}

run "rejects_other_region" {
  command = plan

  variables {
    location = "eastus"
  }

  expect_failures = [var.location]
}

run "api_container_output_for_the_agent_stack" {
  command = plan

  # A known signing key, so the test can check it never appears in the output.
  override_resource {
    target          = random_password.turn_token_signing_key
    override_during = plan
    values = {
      result = "synthetic-signing-key-must-not-leak"
    }
  }

  assert {
    condition     = output.api_container.name == "api"
    error_message = "api_container.name must be the api container's name."
  }

  assert {
    condition     = output.api_container.resources.cpu == 0.25 && output.api_container.resources.memory == "0.5Gi"
    error_message = "api_container.resources must mirror the container's cpu and memory."
  }

  assert {
    condition     = jsonencode(output.api_container.env[0]) == jsonencode({ name = "TURN_TOKEN_SIGNING_KEY", secretRef = "turn-token-signing-key" })
    error_message = "api_container.env must reference the signing key by secret name only."
  }

  assert {
    condition = jsonencode([for e in output.api_container.env : e.name]) == jsonencode([
      "TURN_TOKEN_SIGNING_KEY", "FORMAPP_DEPLOYMENT", "DATABASE_HOST", "DATABASE_NAME", "DATABASE_USER", "AZURE_CLIENT_ID",
      "DATABASE_SSLMODE", "DB_MIGRATION_ROLE", "APPLICATIONINSIGHTS_CONNECTION_STRING", "TELEMETRY_SAMPLING_RATIO",
      "LOG_LEVEL",
    ])
    error_message = "api_container.env must carry every api setting the container has, so the agent PATCH keeps them."
  }

  assert {
    condition     = length(output.api_container.probes) == 3
    error_message = "api_container must carry the startup, readiness and liveness probes, so the agent PATCH keeps them."
  }

  assert {
    condition     = !strcontains(jsonencode(output.api_container), "synthetic-signing-key-must-not-leak")
    error_message = "api_container must never carry a secret value."
  }

  assert {
    condition     = !contains(keys(output.api_container), "image")
    error_message = "api_container must not carry the image; the agent stack sets it."
  }

  assert {
    condition     = output.container_registry_name == "crsampledemosea"
    error_message = "container_registry_name must be the registry's name."
  }
}

run "api_settings_and_probes" {
  command = plan

  assert {
    condition = {
      for e in azurerm_container_app.api.template[0].container[0].env : e.name => e.value if e.value != null
      } == {
      FORMAPP_DEPLOYMENT       = "demo"
      DATABASE_HOST            = "pgsql-sample-demo-sea.postgres.database.azure.com"
      DATABASE_NAME            = "formapp"
      DATABASE_USER            = "id-sample-demo-sea-api"
      AZURE_CLIENT_ID          = "00000000-0000-0000-0000-0000000000c1"
      DATABASE_SSLMODE         = "verify-full"
      DB_MIGRATION_ROLE        = "formapp_migrator"
      TELEMETRY_SAMPLING_RATIO = "1"
      LOG_LEVEL                = "INFO"
    }
    error_message = "The api container must get its database and deployment settings as plain environment variables."
  }

  assert {
    condition     = !anytrue([for e in azurerm_container_app.api.template[0].container[0].env : strcontains(upper(e.name), "PASSWORD")])
    error_message = "api signs in to PostgreSQL with an Entra token; no password setting (AD-10)."
  }

  assert {
    condition = (
      azurerm_container_app.api.template[0].container[0].startup_probe[0].path == "/healthz"
      && azurerm_container_app.api.template[0].container[0].readiness_probe[0].path == "/readyz"
      && azurerm_container_app.api.template[0].container[0].liveness_probe[0].path == "/healthz"
    )
    error_message = "Startup and liveness probes must use /healthz, readiness /readyz."
  }

  assert {
    condition = alltrue([
      azurerm_container_app.api.template[0].container[0].startup_probe[0].port == 8080,
      azurerm_container_app.api.template[0].container[0].readiness_probe[0].port == 8080,
      azurerm_container_app.api.template[0].container[0].liveness_probe[0].port == 8080,
    ])
    error_message = "Every probe must target port 8080, the api container's port."
  }

  assert {
    condition = jsonencode(output.api_container.probes) == jsonencode([
      {
        type                = "Startup"
        httpGet             = { path = "/healthz", port = 8080, scheme = "HTTP" }
        initialDelaySeconds = 1
        periodSeconds       = 5
        timeoutSeconds      = 3
        failureThreshold    = 12
      },
      {
        type                = "Readiness"
        httpGet             = { path = "/readyz", port = 8080, scheme = "HTTP" }
        initialDelaySeconds = 0
        periodSeconds       = 10
        timeoutSeconds      = 5
        failureThreshold    = 3
        successThreshold    = 1
      },
      {
        type                = "Liveness"
        httpGet             = { path = "/healthz", port = 8080, scheme = "HTTP" }
        initialDelaySeconds = 1
        periodSeconds       = 10
        timeoutSeconds      = 3
        failureThreshold    = 3
      },
    ])
    error_message = "api_container.probes must mirror the container's probes in the ARM shape."
  }
}

# ---------------------------------------------------------------------------
# Story 1.5: monitoring and logging
# ---------------------------------------------------------------------------
run "story_1_5_application_insights_is_workspace_based" {
  command = plan

  override_resource {
    target          = module.log_analytics_workspace.azurerm_log_analytics_workspace.this
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.OperationalInsights/workspaces/log-sample-demo-sea"
    }
  }

  assert {
    condition     = module.application_insights.name == "appi-sample-demo-sea"
    error_message = "Application Insights must be named appi-sample-demo-sea."
  }

  assert {
    condition     = endswith(module.application_insights.workspace_id, "/workspaces/log-sample-demo-sea")
    error_message = "Application Insights must be workspace-based on log-sample-demo-sea (azure.md rule 14)."
  }
}

run "story_1_5_owner_is_alerted_at_90_percent_of_the_daily_cap" {
  command = plan

  override_resource {
    target          = azurerm_monitor_action_group.owner
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/actionGroups/ag-sample-demo-sea"
    }
  }

  assert {
    condition     = toset(azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.action[0].action_groups) == toset([azurerm_monitor_action_group.owner.id])
    error_message = "The cap alert must notify the owner's action group."
  }

  assert {
    condition     = azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.auto_mitigation_enabled
    error_message = "The cap alert must be stateful (auto-mitigated), so it emails once rather than every 30 minutes."
  }

  assert {
    condition = (
      azurerm_monitor_action_group.owner.name == "ag-sample-demo-sea"
      && azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.name == "ar-sample-demo-sea-log-cap"
    )
    error_message = "The action group and alert rule names must come from locals.tf (ag-, ar- prefixes)."
  }

  assert {
    condition     = length(azurerm_monitor_action_group.owner.short_name) <= 12
    error_message = "An action group short name has at most 12 characters."
  }

  assert {
    condition     = toset([for r in azurerm_monitor_action_group.owner.email_receiver : r.email_address]) == toset(var.budget_alert_emails)
    error_message = "The action group must email the owner (budget_alert_emails)."
  }

  assert {
    condition     = azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.criteria[0].threshold == 450
    error_message = "The alert must fire at 90% of the 0.5 GB daily cap (450 MB)."
  }

  assert {
    condition = (
      azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.criteria[0].operator == "GreaterThanOrEqual"
      && azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.criteria[0].metric_measure_column == "BillableMB"
      && strcontains(azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.criteria[0].query, "Usage")
      && strcontains(azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.criteria[0].query, "IsBillable == true")
      && strcontains(azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.criteria[0].query, "ago(1d)")
    )
    error_message = "The alert must sum the last 24 hours' billable Usage in MB and compare it with the threshold."
  }

  assert {
    condition = (
      azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.evaluation_frequency == "PT30M"
      && azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.window_duration == "P1D"
      && azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.location == "southeastasia"
    )
    error_message = "The alert must run every 30 minutes over the day, in southeastasia."
  }

  assert {
    condition = (
      jsonencode(azurerm_monitor_scheduled_query_rules_alert_v2.log_cap.tags) == jsonencode(local.tags)
      && jsonencode(azurerm_monitor_action_group.owner.tags) == jsonencode(local.tags)
    )
    error_message = "The alert rule and action group must carry the six required tags."
  }
}

# ---------------------------------------------------------------------------
# Story 4.5: the AI-write isolation alert (AC15, AD-4, AD-9, AD-17, security.md rule 38)
# ---------------------------------------------------------------------------
# Plan-only, no live Log Analytics: asserts the KQL text encodes both fire-conditions (a
# cross-proposal write, and an unknown-or-ended turn ID) and that a normal turn matches neither,
# the same precedent the log_cap alert's own test above already uses (no live KQL locally).
run "story_4_5_ai_write_isolation_alert_fires_on_both_conditions" {
  command = plan

  override_resource {
    target          = azurerm_monitor_action_group.owner
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/actionGroups/ag-sample-demo-sea"
    }
  }

  override_resource {
    target          = module.log_analytics_workspace.azurerm_log_analytics_workspace.this
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.OperationalInsights/workspaces/log-sample-demo-sea"
    }
  }

  assert {
    condition = (
      azurerm_monitor_scheduled_query_rules_alert_v2.ai_write_isolation.name == "ar-sample-demo-sea-ai-write-isolation"
      && toset(azurerm_monitor_scheduled_query_rules_alert_v2.ai_write_isolation.action[0].action_groups) == toset([azurerm_monitor_action_group.owner.id])
      && azurerm_monitor_scheduled_query_rules_alert_v2.ai_write_isolation.scopes[0] == module.log_analytics_workspace.id
    )
    error_message = "The alert must be named ar-<suffix>-ai-write-isolation, scoped to the Log Analytics workspace and notify the owner's action group."
  }

  assert {
    condition     = azurerm_monitor_scheduled_query_rules_alert_v2.ai_write_isolation.auto_mitigation_enabled
    error_message = "The alert must be stateful (auto-mitigated), so it emails once per episode."
  }

  assert {
    condition = (
      azurerm_monitor_scheduled_query_rules_alert_v2.ai_write_isolation.criteria[0].operator == "GreaterThan"
      && azurerm_monitor_scheduled_query_rules_alert_v2.ai_write_isolation.criteria[0].threshold == 0
      && azurerm_monitor_scheduled_query_rules_alert_v2.ai_write_isolation.criteria[0].metric_measure_column == "SuspiciousWrites"
    )
    error_message = "The alert must fire the moment even one suspicious write is summarized (threshold 0)."
  }

  assert {
    condition = alltrue([
      strcontains(local.ai_write_isolation_query, "let AppLogs = ContainerAppConsoleLogs_CL\n"),
      strcontains(local.ai_write_isolation_query, "Entry.event == \"turn_start\""),
      strcontains(local.ai_write_isolation_query, "Entry.event == \"turn_end\""),
      strcontains(local.ai_write_isolation_query, "Entry.event == \"ai_write\""),
    ])
    error_message = "The query must read turn_start/turn_end/ai_write log rows from ContainerAppConsoleLogs_CL, the table logs_destination = log-analytics writes (its columns carry the _s suffix; the resource-specific ContainerAppConsoleLogs table has none)."
  }

  assert {
    condition     = strcontains(local.ai_write_isolation_query, "CrossProposalWrite = isnotempty(StartProposalId) and WriteProposalId != StartProposalId")
    error_message = "Fire-condition 1: a write's proposal_id must be compared against its own turn_start's proposal_id."
  }

  assert {
    condition     = strcontains(local.ai_write_isolation_query, "UnknownOrEndedTurn = isempty(StartProposalId) or (isnotempty(EndedAt) and EndedAt < WriteTime)")
    error_message = "Fire-condition 2: a write with no matching turn_start (unknown) or whose turn already ended before the write (stale/replayed) must be flagged."
  }

  assert {
    condition     = strcontains(local.ai_write_isolation_query, "where CrossProposalWrite or UnknownOrEndedTurn")
    error_message = "Only these two conditions -- not a merely-different-looking write -- select the rows the alert counts: a normal write (its turn's own proposal, not yet ended) matches neither and is never counted."
  }
}

run "story_1_5_postgresql_sends_only_its_server_logs" {
  command = plan

  assert {
    condition     = [for l in azurerm_monitor_diagnostic_setting.postgresql.enabled_log : l.category] == ["PostgreSQLLogs"]
    error_message = "PostgreSQL must send only PostgreSQLLogs (azure.md rule 15)."
  }

  assert {
    condition     = length(azurerm_monitor_diagnostic_setting.postgresql.enabled_metric) == 0
    error_message = "PostgreSQL must send no metrics through its diagnostic setting."
  }

  assert {
    condition     = azurerm_monitor_diagnostic_setting.postgresql.target_resource_id == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.DBforPostgreSQL/flexibleServers/pgsql-sample-demo-sea"
    error_message = "The diagnostic setting must target the PostgreSQL server."
  }
}

run "story_1_5_connection_string_is_a_secret_reference_only" {
  command = plan

  override_resource {
    target          = module.application_insights.azurerm_application_insights.this
    override_during = plan
    values = {
      id                = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/components/appi-sample-demo-sea"
      connection_string = "InstrumentationKey=00000000-5157-4a11-9000-00000000c0de;IngestionEndpoint=https://synthetic-ingest.example.test/"
    }
  }

  assert {
    condition     = contains([for s in azurerm_container_app.api.secret : s.name], "appinsights-connection-string")
    error_message = "The connection string must be a Container Apps secret."
  }

  assert {
    condition = [
      for e in azurerm_container_app.api.template[0].container[0].env : e.secret_name
      if e.name == "APPLICATIONINSIGHTS_CONNECTION_STRING"
    ] == ["appinsights-connection-string"]
    error_message = "APPLICATIONINSIGHTS_CONNECTION_STRING must reference the secret (secretRef), not carry a value."
  }

  assert {
    condition     = contains(output.api_container.env, { name = "APPLICATIONINSIGHTS_CONNECTION_STRING", secretRef = "appinsights-connection-string" })
    error_message = "api_container must carry the connection string by secret name only, so the agent PATCH keeps it."
  }

  assert {
    condition     = contains(output.api_container.env, { name = "TELEMETRY_SAMPLING_RATIO", value = "1" })
    error_message = "api_container must carry the sampling ratio."
  }

  assert {
    condition     = !strcontains(jsonencode(output.api_container), "00000000-5157-4a11-9000-00000000c0de")
    error_message = "No output may carry the connection string."
  }
}

run "story_1_5_rejects_sampling_ratio_above_one" {
  command = plan

  variables {
    telemetry_sampling_ratio = 1.5
  }

  expect_failures = [var.telemetry_sampling_ratio]
}

run "story_1_5_rejects_sampling_ratio_below_zero" {
  command = plan

  variables {
    telemetry_sampling_ratio = -0.1
  }

  expect_failures = [var.telemetry_sampling_ratio]
}

run "story_1_5_rejects_cap_alert_percent_of_zero" {
  command = plan

  variables {
    log_analytics_cap_alert_percent = 0
  }

  expect_failures = [var.log_analytics_cap_alert_percent]
}

run "story_1_5_rejects_cap_alert_percent_above_100" {
  command = plan

  variables {
    log_analytics_cap_alert_percent = 101
  }

  expect_failures = [var.log_analytics_cap_alert_percent]
}

run "story_1_5_rejects_no_alert_emails" {
  command = plan

  variables {
    budget_alert_emails = []
  }

  expect_failures = [var.budget_alert_emails]
}

run "story_1_5_rejects_a_zero_daily_cap" {
  command = plan

  variables {
    log_analytics_daily_quota_gb = 0
  }

  expect_failures = [var.log_analytics_daily_quota_gb]
}

run "story_1_5_rejects_unknown_log_level" {
  command = plan

  variables {
    api_log_level = "chatty"
  }

  expect_failures = [var.api_log_level]
}

run "story_1_5_api_identity_publishes_telemetry_with_entra" {
  command = plan

  assert {
    condition     = azurerm_role_assignment.api_monitoring_publisher.role_definition_name == "Monitoring Metrics Publisher"
    error_message = "The api identity must get Monitoring Metrics Publisher."
  }

  assert {
    condition     = azurerm_role_assignment.api_monitoring_publisher.scope == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/components/appi-sample-demo-sea"
    error_message = "The role must be scoped to the Application Insights resource only."
  }

  assert {
    condition     = azurerm_role_assignment.api_monitoring_publisher.principal_id == "00000000-0000-0000-0000-0000000000d1"
    error_message = "The role must go to the api identity."
  }

  assert {
    condition     = azurerm_role_assignment.api_monitoring_publisher.principal_type == "ServicePrincipal"
    error_message = "principal_type must be ServicePrincipal (the pipeline's RBAC Administrator condition requires it)."
  }
}

run "postgresql_public_access_rule_follows_the_variable" {
  command = plan

  variables {
    postgresql_allow_public_access = true
  }

  assert {
    condition     = module.postgresql_flexible_server.public_access_ip_range == "0.0.0.0-255.255.255.255"
    error_message = "With postgresql_allow_public_access = true, the temporary allow-all rule must span 0.0.0.0-255.255.255.255."
  }

  assert {
    condition     = output.postgresql_public_access == true
    error_message = "The deploy reads postgresql_public_access to skip its runner rule."
  }
}

run "postgresql_public_access_off_removes_the_rule" {
  command = plan

  variables {
    postgresql_allow_public_access = false
  }

  assert {
    condition     = module.postgresql_flexible_server.public_access_ip_range == null
    error_message = "With postgresql_allow_public_access = false, no allow-all rule may exist."
  }
}

# ---------------------------------------------------------------------------
# Story 1.6: sign-in (Container Apps authentication) and its token store
# ---------------------------------------------------------------------------
run "story_1_6_entra_sign_in_allows_anonymous_with_the_token_store_on" {
  command = plan

  assert {
    condition     = azapi_resource.api_auth.name == "current" && azapi_resource.api_auth.type == "Microsoft.App/containerApps/authConfigs@2026-07-01"
    error_message = "Sign-in must be the Container App's authConfigs resource named current, pinned to GA API 2026-07-01 (the first stable version with the managed-identity token store)."
  }

  assert {
    condition     = azapi_resource.api_auth.parent_id == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.App/containerApps/ca-sample-demo-sea"
    error_message = "authConfigs must belong to the api Container App."
  }

  assert {
    condition     = azapi_resource.api_auth.body.properties.globalValidation.unauthenticatedClientAction == "AllowAnonymous"
    error_message = "Unauthenticated requests must be allowed, so the Welcome page loads (azure.md rule 12)."
  }

  assert {
    condition     = azapi_resource.api_auth.body.properties.platform.enabled && azapi_resource.api_auth.body.properties.httpSettings.requireHttps
    error_message = "Sign-in must be on, over HTTPS only."
  }

  assert {
    condition     = azapi_resource.api_auth.body.properties.identityProviders.azureActiveDirectory.enabled
    error_message = "Entra ID must be the identity provider."
  }

  assert {
    condition     = azapi_resource.api_auth.body.properties.identityProviders.azureActiveDirectory.registration.openIdIssuer == "https://login.microsoftonline.com/00000000-0000-0000-0000-00000000000a/v2.0"
    error_message = "The issuer must be this tenant's v2.0 endpoint (single-tenant sign-in)."
  }

  assert {
    condition     = azapi_resource.api_auth.body.properties.identityProviders.azureActiveDirectory.registration.clientId == var.entra_signin_client_id
    error_message = "The client ID must come from the non-secret entra_signin_client_id input."
  }

  assert {
    condition     = !strcontains(lower(jsonencode(azapi_resource.api_auth.body)), "secret")
    error_message = "Sign-in must have no client secret: the signing key stays the only app secret (azure.md rule 10)."
  }

  assert {
    condition     = azapi_resource.api_auth.body.properties.login.tokenStore.enabled
    error_message = "The token store must be on."
  }

  assert {
    condition     = azapi_resource.api_auth.body.properties.login.tokenStore.azureBlobStorage.blobContainerUri == "https://stsampledemosea.blob.core.windows.net/tokenstore"
    error_message = "The token store must be the tokenstore container in stsampledemosea."
  }

  assert {
    condition     = azapi_resource.api_auth.body.properties.login.tokenStore.azureBlobStorage.managedIdentityResourceId == module.api_identity.id
    error_message = "The token store must be reached with the api managed identity, never a SAS URL."
  }
}

# The storage-account module has no tests of its own (owner decision, 2026-09-27, POC only); a
# root test can't read a nested module's resources, so only the account name is checked here.
run "story_1_6_token_store_account_name" {
  command = plan

  assert {
    condition     = local.names.storage_account == "stsampledemosea" && module.token_store.name == "stsampledemosea"
    error_message = "The token-store account must be stsampledemosea (azure.md naming table)."
  }
}

run "story_1_6_api_identity_gets_blob_data_contributor_on_the_container_only" {
  command = plan

  assert {
    condition     = azurerm_role_assignment.api_token_store.role_definition_name == "Storage Blob Data Contributor"
    error_message = "The api identity must get Storage Blob Data Contributor for the token store."
  }

  assert {
    condition     = azurerm_role_assignment.api_token_store.scope == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Storage/storageAccounts/stsampledemosea/blobServices/default/containers/tokenstore"
    error_message = "The blob role must be scoped to the tokenstore container, never wider."
  }

  assert {
    condition     = azurerm_role_assignment.api_token_store.principal_id == "00000000-0000-0000-0000-0000000000d1" && azurerm_role_assignment.api_token_store.principal_type == "ServicePrincipal"
    error_message = "The role must go to the api identity as a ServicePrincipal (the RBAC Administrator condition requires it)."
  }
}

run "story_1_6_rejects_all_zero_sign_in_client_id" {
  command = plan

  variables {
    entra_signin_client_id = "00000000-0000-0000-0000-000000000000"
  }

  expect_failures = [var.entra_signin_client_id]
}

run "story_1_6_rejects_non_guid_sign_in_client_id" {
  command = plan

  variables {
    entra_signin_client_id = "formapp-sign-in"
  }

  expect_failures = [var.entra_signin_client_id]
}

# ---------------------------------------------------------------------------
# Story 4.1: Foundry account, project, model deployment and roles
# ---------------------------------------------------------------------------
run "story_4_1_foundry_names_and_outputs_for_the_agent_stack" {
  command = plan

  assert {
    condition     = module.foundry.account_name == "aif-sample-demo-sea" && module.foundry.project_name == "proj-sample-demo-sea"
    error_message = "The Foundry account and project must be aif-sample-demo-sea and proj-sample-demo-sea (names from locals.tf)."
  }

  assert {
    condition     = output.foundry_project_endpoint == "https://aif-sample-demo-sea.services.ai.azure.com/api/projects/proj-sample-demo-sea"
    error_message = "foundry_project_endpoint must be the project's data-plane endpoint."
  }

  assert {
    condition     = output.model_deployment_name == "gpt-5.4-mini"
    error_message = "model_deployment_name must be the active gpt-5.4-mini deployment (FORM-226), the only way its name reaches code."
  }

  assert {
    condition = (
      module.foundry.model_deployment_names == ["gpt-4.1-mini", "gpt-5.4-mini"]
      && module.foundry.model_deployment_name == "gpt-5.4-mini"
    )
    error_message = "gpt-4.1-mini must stay deployed for rollback next to the active gpt-5.4-mini (FORM-226)."
  }

  assert {
    condition     = output.hosted_agent_name == "formapp-agent"
    error_message = "hosted_agent_name must be formapp-agent."
  }
}

run "story_4_1_api_identity_is_foundry_user_on_the_project_only" {
  command = plan

  assert {
    condition     = azurerm_role_assignment.api_foundry_user.role_definition_id == "/subscriptions/00000000-0000-0000-0000-00000000000b/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
    error_message = "api must get Foundry User (formerly Azure AI User), by role ID."
  }

  assert {
    condition     = azurerm_role_assignment.api_foundry_user.scope == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/aif-sample-demo-sea/projects/proj-sample-demo-sea"
    error_message = "api's Foundry User role must be scoped to the project only (NFR16)."
  }

  assert {
    condition = (
      azurerm_role_assignment.api_foundry_user.principal_id == "00000000-0000-0000-0000-0000000000d1"
      && azurerm_role_assignment.api_foundry_user.principal_type == "ServicePrincipal"
    )
    error_message = "The role must go to the api identity, as a service principal (the pipeline's RBAC condition)."
  }
}

run "story_4_1_project_identity_pulls_the_agent_image" {
  command = plan

  assert {
    condition = (
      azurerm_role_assignment.project_acr_pull.role_definition_name == "AcrPull"
      && azurerm_role_assignment.project_acr_pull.principal_id == "00000000-0000-0000-0000-0000000000e1"
      && azurerm_role_assignment.project_acr_pull.principal_type == "ServicePrincipal"
    )
    error_message = "The project's system identity must get AcrPull, as a service principal."
  }

  assert {
    condition     = azurerm_role_assignment.project_acr_pull.scope == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.ContainerRegistry/registries/crsampledemosea"
    error_message = "AcrPull must be scoped to the registry only."
  }
}

run "story_4_1_project_is_connected_to_application_insights" {
  command = plan

  override_resource {
    target          = module.application_insights.azurerm_application_insights.this
    override_during = plan
    values = {
      id                = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/components/appi-sample-demo-sea"
      connection_string = "InstrumentationKey=00000000-5157-4a11-9000-00000000c0de;IngestionEndpoint=https://synthetic-ingest.example.test/"
    }
  }

  assert {
    condition = (
      azapi_resource.foundry_appinsights_connection.body.properties.category == "AppInsights"
      && azapi_resource.foundry_appinsights_connection.body.properties.target == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/components/appi-sample-demo-sea"
      && azapi_resource.foundry_appinsights_connection.body.properties.metadata.ResourceId == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/components/appi-sample-demo-sea"
    )
    error_message = "Foundry must be connected to the one Application Insights instance (azure.md rule 14)."
  }

  assert {
    condition     = azapi_resource.foundry_appinsights_connection.body.properties.authType == "ProjectManagedIdentity"
    error_message = "The connection must authenticate with Entra (Application Insights has local auth off), never an API key."
  }

  assert {
    condition     = azapi_resource.foundry_appinsights_connection.parent_id == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/aif-sample-demo-sea/projects/proj-sample-demo-sea"
    error_message = "The connection must belong to the Foundry project, not the account, or Foundry won't inject APPLICATIONINSIGHTS_CONNECTION_STRING into the hosted agent or show traces."
  }

  assert {
    condition = (
      azurerm_role_assignment.project_monitoring_publisher.role_definition_name == "Monitoring Metrics Publisher"
      && azurerm_role_assignment.project_monitoring_publisher.scope == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/components/appi-sample-demo-sea"
      && azurerm_role_assignment.project_monitoring_publisher.principal_id == "00000000-0000-0000-0000-0000000000e1"
      && azurerm_role_assignment.project_monitoring_publisher.principal_type == "ServicePrincipal"
    )
    error_message = "The project's own system identity must get Monitoring Metrics Publisher on Application Insights, for Foundry Agent Service's server-side traces."
  }

  assert {
    condition = !anytrue([
      for o in [output.foundry_project_endpoint, output.model_deployment_name, output.hosted_agent_name, jsonencode(output.hosted_agent_role_assignments), jsonencode(output.api_container)] :
      strcontains(o, "00000000-5157-4a11-9000-00000000c0de")
    ])
    error_message = "No output may carry the Application Insights connection string."
  }
}

run "story_4_1_foundry_sends_audit_and_request_logs_to_the_workspace" {
  command = plan

  override_resource {
    target          = module.log_analytics_workspace.azurerm_log_analytics_workspace.this
    override_during = plan
    values = {
      id = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.OperationalInsights/workspaces/log-sample-demo-sea"
    }
  }

  assert {
    condition     = toset([for l in azurerm_monitor_diagnostic_setting.foundry.enabled_log : l.category]) == toset(["Audit", "RequestResponse"])
    error_message = "Foundry must send only its Audit and RequestResponse logs (azure.md rule 15)."
  }

  assert {
    condition     = length(azurerm_monitor_diagnostic_setting.foundry.enabled_metric) == 0
    error_message = "Foundry must send no metrics through its diagnostic setting."
  }

  assert {
    condition = (
      azurerm_monitor_diagnostic_setting.foundry.target_resource_id == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/aif-sample-demo-sea"
      && azurerm_monitor_diagnostic_setting.foundry.log_analytics_workspace_id == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.OperationalInsights/workspaces/log-sample-demo-sea"
    )
    error_message = "The diagnostic setting must send the Foundry account's logs to log-sample-demo-sea."
  }
}

run "story_4_1_hosted_agent_roles_for_the_agent_stack" {
  command = plan

  assert {
    condition = jsonencode(output.hosted_agent_role_assignments) == jsonencode({
      foundry_user = {
        role_definition_id = "/subscriptions/00000000-0000-0000-0000-00000000000b/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
        scope              = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/aif-sample-demo-sea/projects/proj-sample-demo-sea"
      }
      monitoring_metrics_publisher = {
        role_definition_id = "/subscriptions/00000000-0000-0000-0000-00000000000b/providers/Microsoft.Authorization/roleDefinitions/3913510d-42f4-4e42-8a64-420c390055eb"
        scope              = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/components/appi-sample-demo-sea"
      }
    })
    error_message = "The hosted agent's identity must get Foundry User on the project and Monitoring Metrics Publisher on Application Insights, nothing else (azure.md rule 9)."
  }
}

run "story_4_1_container_env_and_the_patch_share_one_source" {
  command = plan

  assert {
    condition = jsonencode([for e in azurerm_container_app.api.template[0].container[0].env : e.name]) == jsonencode([
      for e in output.api_container.env : e.name
    ])
    error_message = "The container's first env and the api_container env the agent stack resends must both come from local.api_env."
  }

  assert {
    condition     = !anytrue([for e in output.api_container.env : startswith(e.name, "FOUNDRY_")])
    error_message = "foundation must not set the agent env on api; the agent stack adds it once Foundry exists."
  }
}
