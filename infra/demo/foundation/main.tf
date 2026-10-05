data "azurerm_client_config" "current" {}

# ---------------------------------------------------------------------------
# Resource group: created (with the six tags) by infra/bootstrap/state-backend.sh,
# adopted here so the pipeline identity never needs subscription-scope rights.
# ---------------------------------------------------------------------------
import {
  to = module.resource_group.module.resource_group.azapi_resource.this
  id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${local.names.resource_group}"
}

module "resource_group" {
  source = "../../modules/resource-group"

  name     = local.names.resource_group
  location = var.location
  tags     = local.tags
}

# ---------------------------------------------------------------------------
# Registry, logs, identity
# ---------------------------------------------------------------------------
module "container_registry" {
  source = "../../modules/container-registry"

  name                = local.names.container_registry
  resource_group_name = module.resource_group.name
  location            = var.location
  sku                 = var.container_registry_sku
  tags                = local.tags
}

module "log_analytics_workspace" {
  source = "../../modules/log-analytics-workspace"

  name                = local.names.log_analytics_workspace
  resource_group_name = module.resource_group.name
  location            = var.location
  retention_in_days   = var.log_analytics_retention_in_days
  daily_quota_gb      = var.log_analytics_daily_quota_gb
  tags                = local.tags
}

# Story 1.5: the one workspace-based Application Insights, on the workspace above (azure.md rule 14).
module "application_insights" {
  source = "../../modules/application-insights"

  name                = local.names.application_insights
  resource_group_name = module.resource_group.name
  location            = var.location
  workspace_id        = module.log_analytics_workspace.id
  tags                = local.tags
}

# api sends telemetry with its managed identity; Application Insights refuses key-only ingestion.
# principal_type is set because the pipeline identity's RBAC Administrator condition only allows
# assignments to service principals.
resource "azurerm_role_assignment" "api_monitoring_publisher" {
  scope                = module.application_insights.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = module.api_identity.principal_id
  principal_type       = "ServicePrincipal"
}

# ---------------------------------------------------------------------------
# Foundry (Story 4.1): account, project, capability host and model deployment
# ---------------------------------------------------------------------------
module "foundry" {
  source = "../../modules/foundry"

  account_name            = local.names.foundry_account
  project_name            = local.names.foundry_project
  resource_group_name     = module.resource_group.name
  location                = var.location
  sku_name                = var.foundry_sku_name
  capability_host_name    = local.foundry_capability_host_name
  model_deployment_name   = local.foundry_model_deployment_name
  model_format            = var.foundry_model_format
  model_name              = var.foundry_model_name
  model_version           = var.foundry_model_version
  model_sku_name          = var.foundry_model_sku_name
  model_capacity          = var.foundry_model_capacity
  next_model_deployment   = var.foundry_next_model
  active_model_deployment = var.foundry_active_model_deployment
  tags                    = local.tags
}

# Connects the Foundry *project* (not the account) to the one Application Insights instance
# (azure.md rule 14). Foundry injects APPLICATIONINSIGHTS_CONNECTION_STRING into the hosted agent
# container, and the Traces tab reads traces, only from a connection on the project itself, never an
# account-level one (Microsoft Learn, "Export hosted agent telemetry by using OpenTelemetry": "Foundry
# injects this setting automatically when project monitoring is enabled"; "Set up tracing for AI
# agents": the Traces tab's Connect wizard creates a project connection). authType
# ProjectManagedIdentity, no credentials: Application Insights has local authentication off, so
# ingestion authorises by Entra token. The API accepts only ProjectManagedIdentity or ApiKey for an
# AppInsights connection (deploy run 36285075738 rejected "AAD": "AuthType for AppInsights Connection
# can only be ProjectManagedIdentity, ApiKey"). azapi: azurerm has no resource for project-level
# connections (terraform.md rule 12). API version 2026-05-01, the latest stable version azapi 2.12.0's
# embedded schema knows for this resource type (a newer GA, 2026-07-01, exists but isn't in that
# schema yet; terraform.md rule 9). That schema's authType enum lacks ProjectManagedIdentity, so
# schema validation is off for this one resource. The API also requires the connection string in
# metadata (deploy run 36285441674: "Required metadata property ApplicationInsightsConnectionString is
# missing"); it goes in sensitive_body so plans don't print it, but Azure stores connection metadata in
# plain text. Accepted by the owner (2026-09-27): with local auth off, the string alone can't send
# telemetry.
resource "azapi_resource" "foundry_appinsights_connection" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01"
  name      = local.foundry_appinsights_connection
  parent_id = module.foundry.project_id

  schema_validation_enabled = false

  body = {
    properties = {
      category = "AppInsights"
      target   = module.application_insights.id
      authType = "ProjectManagedIdentity"

      metadata = {
        ApiType    = "Azure"
        ResourceId = module.application_insights.id
      }
    }
  }

  sensitive_body = {
    properties = {
      metadata = {
        ApplicationInsightsConnectionString = module.application_insights.connection_string
      }
    }
  }
}

# The earlier account-level App Insights connection, replaced by the project connection above.
# Terraform forgets it without deleting it: the deploy guard (infra/scripts/plan-guard.sh) blocks
# deleting any Foundry resource, and the owner chose to keep the guard as is (owner, 2026-09-27). The
# unused connection stays on the account until the owner removes it in the portal.
removed {
  from = azurerm_cognitive_account_connection_api_key.application_insights

  lifecycle {
    destroy = false
  }
}

# Foundry Agent Service emits the hosted agent's server-side traces using the project's own system
# identity, separately from the hosted agent's own Entra identity (which emits traces from code
# running in the agent sandbox; its own Monitoring Metrics Publisher role is
# hosted_agent_role_assignments, assigned once the agent stack creates that identity). Both identities
# need the role, because hosted-agent traces come from both (Microsoft Learn, "Configure Microsoft
# Entra authentication for Foundry Agent trace ingestion": "Set up Entra authentication for hosted
# agent traces").
resource "azurerm_role_assignment" "project_monitoring_publisher" {
  scope                = module.application_insights.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = module.foundry.project_principal_id
  principal_type       = "ServicePrincipal"
}

# Foundry audit and request logs to the workspace (azure.md rule 15), no metrics.
resource "azurerm_monitor_diagnostic_setting" "foundry" {
  name                       = local.foundry_diagnostic_setting_name
  target_resource_id         = module.foundry.account_id
  log_analytics_workspace_id = module.log_analytics_workspace.id

  dynamic "enabled_log" {
    for_each = toset(local.foundry_diagnostic_log_categories)

    content {
      category = enabled_log.value
    }
  }
}

# api calls the hosted agent's Responses endpoint as its managed identity (azure.md rule 9). By role
# ID: the display name changed from Azure AI User to Foundry User.
resource "azurerm_role_assignment" "api_foundry_user" {
  scope              = module.foundry.project_id
  role_definition_id = local.role_definition_ids.foundry_user
  principal_id       = module.api_identity.principal_id
  principal_type     = "ServicePrincipal"
}

# The project's system identity pulls the hosted-agent image (Microsoft Learn, "Hosted agent
# permissions reference": image pulls use the project managed identity). The running container
# uses the agent's own Entra identity instead; the agent stack assigns its roles.
resource "azurerm_role_assignment" "project_acr_pull" {
  scope                = module.container_registry.id
  role_definition_name = "AcrPull"
  principal_id         = module.foundry.project_principal_id
  principal_type       = "ServicePrincipal"
}

module "api_identity" {
  source = "../../modules/user-assigned-identity"

  name                = local.names.api_identity
  resource_group_name = module.resource_group.name
  location            = var.location
  tags                = local.tags
}

# The api identity's only role here: pull images from this registry (azure.md rule 9).
# principal_type is set explicitly because the pipeline identity's RBAC Administrator
# condition only allows assignments to service principals.
resource "azurerm_role_assignment" "api_acr_pull" {
  scope                = module.container_registry.id
  role_definition_name = "AcrPull"
  principal_id         = module.api_identity.principal_id
  principal_type       = "ServicePrincipal"
}

# ---------------------------------------------------------------------------
# Speech (Story 6.1, AD-19): a dedicated Speech account and identity, so a browser token never
# reaches Speech through api's own (Foundry-scoped) identity.
# ---------------------------------------------------------------------------
# Hand-written azurerm (terraform.md rule 15): a single resource, unlike Foundry's multi-child
# account/project/deployment set, so it doesn't need its own module (terraform.md rule 12 reasoning
# doesn't apply -- azurerm models this resource fully). Custom subdomain is required because
# local_auth_enabled = false needs Entra auth (azure.md rules 5, 8, 19); SpeechServices, S0 (the
# cheapest tier that supports Entra auth).
resource "azurerm_cognitive_account" "speech" {
  name                  = local.names.speech_account
  resource_group_name   = module.resource_group.name
  location              = var.location
  kind                  = "SpeechServices"
  sku_name              = var.speech_sku_name
  custom_subdomain_name = local.names.speech_account
  local_auth_enabled    = false

  tags = local.tags
}

# The dedicated identity a browser token is minted for (AD-19): api's own identity never gets a
# Speech role, so a leaked/short-lived Speech token can't reach anything else api can (azure.md
# rule 9's least-privilege reasoning, applied per identity rather than per role).
module "speech_identity" {
  source = "../../modules/user-assigned-identity"

  name                = local.names.speech_identity
  resource_group_name = module.resource_group.name
  location            = var.location
  tags                = local.tags
}

# By role name, not GUID (unlike Foundry User): "Cognitive Services Speech User" was never renamed,
# so there is no display-name/GUID mismatch to work around.
resource "azurerm_role_assignment" "speech_user" {
  scope                = azurerm_cognitive_account.speech.id
  role_definition_name = "Cognitive Services Speech User"
  principal_id         = module.speech_identity.principal_id
  principal_type       = "ServicePrincipal"
}

# ---------------------------------------------------------------------------
# PostgreSQL (Entra-only auth)
# ---------------------------------------------------------------------------
module "postgresql_flexible_server" {
  source = "../../modules/postgresql-flexible-server"

  name                  = local.names.postgresql_flexible_server
  resource_group_name   = module.resource_group.name
  location              = var.location
  postgresql_version    = var.postgresql_version
  sku_name              = var.postgresql_sku_name
  storage_mb            = var.postgresql_storage_mb
  backup_retention_days = var.postgresql_backup_retention_days
  tenant_id             = data.azurerm_client_config.current.tenant_id
  entra_admin_object_id = var.db_admin_group_object_id
  entra_admin_name      = var.db_admin_group_name

  azure_services_firewall_rule_name = local.postgresql_azure_services_firewall_rule_name
  public_access_firewall_rule_name  = local.postgresql_public_access_firewall_rule_name
  allow_public_access               = var.postgresql_allow_public_access

  tags = local.tags
}

# ---------------------------------------------------------------------------
# Container Apps
# ---------------------------------------------------------------------------
module "container_apps_environment" {
  source = "../../modules/container-apps-environment"

  name                       = local.names.container_apps_environment
  resource_group_name        = module.resource_group.name
  location                   = var.location
  log_analytics_workspace_id = module.log_analytics_workspace.id
  tags                       = local.tags
}

# The only application secret (AD-4). Rotate by changing turn_token_signing_key_rotation.
resource "random_password" "turn_token_signing_key" {
  length  = 64
  special = false

  keepers = {
    rotation = var.turn_token_signing_key_rotation
  }
}

# Hand-written azurerm: AD-11 needs lifecycle.ignore_changes on the container image, and a
# lifecycle block can't be passed into a module call (AVM avm-res-app-containerapp included).
resource "azurerm_container_app" "api" {
  name                         = local.names.container_app
  resource_group_name          = module.resource_group.name
  container_app_environment_id = module.container_apps_environment.id
  revision_mode                = "Single"
  # The environment's Consumption profile (azure.md rule 19); Azure records it on the app, so
  # it is declared here to avoid a plan diff on every deploy.
  workload_profile_name = "Consumption"

  identity {
    type = "UserAssigned"
    # The dedicated speech identity rides along here (so the running container can use it with
    # ManagedIdentityCredential) but never goes in the registry block below or gets AcrPull: only
    # api_identity pulls images (Story 6.1, AD-19).
    identity_ids = [module.api_identity.id, module.speech_identity.id]
  }

  registry {
    server   = module.container_registry.login_server
    identity = module.api_identity.id
  }

  secret {
    name  = local.turn_token_signing_secret_name
    value = random_password.turn_token_signing_key.result
  }

  # Not a credential in the strict sense, but it grants ingestion: a secret keeps it out of the
  # api_container output, remote state outputs and the agent stack's PATCH body (Story 1.5).
  secret {
    name  = local.appinsights_connection_string_secret_name
    value = module.application_insights.connection_string
  }

  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = var.container_app_target_port
    transport                  = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.container_app_min_replicas
    max_replicas = var.container_app_max_replicas

    container {
      name   = local.api_container_name
      image  = var.container_app_placeholder_image
      cpu    = var.container_app_cpu
      memory = var.container_app_memory

      # Built from local.api_env (Story 4.1). Only the first apply sets it: afterwards the agent stack
      # resends it with the agent env on every deploy, and ignore_changes below keeps foundation from
      # fighting that PATCH.
      dynamic "env" {
        for_each = local.api_env

        content {
          name        = env.value.name
          value       = env.value.value
          secret_name = env.value.secret_name
        }
      }

      # Probes (NFR22, azure.md rule 22): /healthz while the process is up, /readyz only when the
      # database is reachable at the image's Alembic head (AD-10). outputs.tf resends them in the
      # agent stack's PATCH, which replaces the whole container.
      startup_probe {
        transport               = "HTTP"
        port                    = var.container_app_target_port
        path                    = local.api_probes.startup.path
        initial_delay           = local.api_probes.startup.initial_delay
        interval_seconds        = local.api_probes.startup.interval_seconds
        timeout                 = local.api_probes.startup.timeout
        failure_count_threshold = local.api_probes.startup.failure_count_threshold
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = var.container_app_target_port
        path                    = local.api_probes.readiness.path
        initial_delay           = local.api_probes.readiness.initial_delay
        interval_seconds        = local.api_probes.readiness.interval_seconds
        timeout                 = local.api_probes.readiness.timeout
        failure_count_threshold = local.api_probes.readiness.failure_count_threshold
        success_count_threshold = local.api_probes.readiness.success_count_threshold
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = var.container_app_target_port
        path                    = local.api_probes.liveness.path
        initial_delay           = local.api_probes.liveness.initial_delay
        interval_seconds        = local.api_probes.liveness.interval_seconds
        timeout                 = local.api_probes.liveness.timeout
        failure_count_threshold = local.api_probes.liveness.failure_count_threshold
      }
    }
  }

  tags = local.tags

  depends_on = [azurerm_role_assignment.api_acr_pull]

  lifecycle {
    # The agent stack sets the image and the environment with azapi_resource_action (PATCH)
    # (AD-11). azurerm can't ignore part of the env list, so the whole list is ignored; its source
    # of truth is local.api_env, which reaches every deploy through the api_container output.
    ignore_changes = [
      template[0].container[0].image,
      template[0].container[0].env,
    ]
  }
}

# ---------------------------------------------------------------------------
# Sign-in (Story 1.6): Container Apps authentication with Entra, and its token store
# ---------------------------------------------------------------------------
# The token store: signed-in sessions live in a private blob container that the api identity reaches
# with Entra (no shared keys, no SAS).
module "token_store" {
  source = "../../modules/storage-account"

  name              = local.names.storage_account
  location          = var.location
  resource_group_id = module.resource_group.id
  # FORM-240 clean-up: this account holds only the sign-in token store again; the feedback export
  # lives on module.feedback_export_storage.
  container_names = [local.token_store_container]
  tags            = local.tags
}

# The api identity reads and writes the token store, on that one container only (azure.md rule 9).
# principal_type is set because the pipeline identity's RBAC Administrator condition only allows
# assignments to service principals.
resource "azurerm_role_assignment" "api_token_store" {
  scope                = module.token_store.container_ids[local.token_store_container]
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = module.api_identity.principal_id
  principal_type       = "ServicePrincipal"
}

# azapi: azurerm 5.7.0 has no Container Apps authentication resource (no
# azurerm_container_app_auth_config, and azurerm_container_app has no auth block), so this is
# Microsoft.App/containerApps/authConfigs (terraform.md rule 12).
#
# GA API 2026-07-01 is the first stable version that accepts the managed-identity token store
# (blobContainerUri, managedIdentityResourceId); earlier GA versions take only a SAS URL. azapi
# 2.12.0's embedded schema stops at 2026-01-01, so schema validation is off for this one resource
# (owner decision, 2026-09-26); turn it back on once a pinned azapi release knows 2026-07-01
# (deferred-work.md). The foundation tests pin the type and the body's token-store keys instead.
#
# Entra is the identity provider; unauthenticated requests are allowed (AllowAnonymous) so the
# signed-out Welcome page loads, and api itself answers 401 on every /api/* path without a principal
# (azure.md rule 12; a known POC exception, security.md section 9). No client secret: sign-in uses
# the ID-token flow, so the turn-token signing key stays the only app secret (azure.md rule 10).
# The app registration is made by hand (infra/README.md); Terraform takes only its client ID.
resource "azapi_resource" "api_auth" {
  type      = "Microsoft.App/containerApps/authConfigs@2026-07-01"
  name      = local.auth_config_name
  parent_id = azurerm_container_app.api.id

  schema_validation_enabled = false

  body = {
    properties = {
      platform = {
        enabled = true
      }
      globalValidation = {
        unauthenticatedClientAction = "AllowAnonymous"
      }
      httpSettings = {
        requireHttps = true
      }
      identityProviders = {
        azureActiveDirectory = {
          enabled = true
          registration = {
            clientId     = var.entra_signin_client_id
            openIdIssuer = local.entra_signin_issuer
          }
        }
      }
      login = {
        tokenStore = {
          enabled = true
          azureBlobStorage = {
            blobContainerUri          = module.token_store.container_urls[local.token_store_container]
            managedIdentityResourceId = module.api_identity.id
          }
        }
      }
    }
  }

  # The token store must be reachable before sign-in is switched on.
  depends_on = [azurerm_role_assignment.api_token_store]
}

# ---------------------------------------------------------------------------
# Nightly feedback job (Story 7.1/FORM-237, spine AD-10, AD-20)
# ---------------------------------------------------------------------------
# FORM-240: a dedicated storage account for the feedback export, so Power BI's per-account
# credential test (it lists every container on the account it's given) never sees the sign-in
# token store's tokenstore container. Same module as the token store, so it gets the same
# hardening (shared keys off, no public blob access, TLS 1.2). Account-level read for
# formapp-feedback-readers is harmless here because this account holds only feedback-export
# (owner decision, 2026-09-28).
module "feedback_export_storage" {
  source = "../../modules/storage-account"

  name              = local.names.feedback_export_storage_account
  location          = var.location
  resource_group_id = module.resource_group.id
  container_names   = [local.feedback_export_container]
  tags              = local.tags
}

# The api identity writes the CSV snapshot (Story 7.3), so Contributor rather than Reader -- scoped
# to this one container, never the account (azure.md rule 9). The reading side (the leads' Power BI
# access) is Reader, at the account scope (FORM-240), for a different principal (an Entra group),
# assigned by infra/bootstrap (state-backend.sh) because the deploy identity's RBAC Administrator
# condition may assign only to service principals.
resource "azurerm_role_assignment" "api_feedback_export_dedicated" {
  scope                = module.feedback_export_storage.container_ids[local.feedback_export_container]
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = module.api_identity.principal_id
  principal_type       = "ServicePrincipal"
}

# Salts the agent hash (a salted SHA-256 of oid) the job writes into the snapshot, so the CSV never
# carries a raw oid (security.md rule 2). Rotate by changing feedback_export_salt_rotation.
resource "random_password" "feedback_export_salt" {
  length  = 64
  special = false

  keepers = {
    rotation = var.feedback_export_salt_rotation
  }
}

# Hand-written azurerm, same reasoning as azurerm_container_app.api above: AD-11's image
# chicken-and-egg (the deploy workflow only builds the api image after this stack applies) needs
# lifecycle.ignore_changes on the container image, and a lifecycle block can't be passed into a
# module call.
resource "azurerm_container_app_job" "feedback" {
  name                         = local.names.container_apps_job
  resource_group_name          = module.resource_group.name
  location                     = var.location
  container_app_environment_id = module.container_apps_environment.id
  # The environment's Consumption profile (azure.md rule 19), declared for the same reason as the
  # api Container App: Azure records it, so an undeclared value would show as a plan diff.
  workload_profile_name      = "Consumption"
  replica_timeout_in_seconds = var.feedback_job_replica_timeout_seconds
  replica_retry_limit        = var.feedback_job_replica_retry_limit

  identity {
    type         = "UserAssigned"
    identity_ids = [module.api_identity.id]
  }

  registry {
    server   = module.container_registry.login_server
    identity = module.api_identity.id
  }

  secret {
    name  = local.feedback_export_salt_secret_name
    value = random_password.feedback_export_salt.result
  }

  schedule_trigger_config {
    cron_expression          = local.feedback_job_cron
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = local.feedback_job_container_name
      image   = var.container_app_placeholder_image
      cpu     = var.feedback_job_cpu
      memory  = var.feedback_job_memory
      command = local.feedback_job_command

      dynamic "env" {
        for_each = local.feedback_job_env

        content {
          name        = env.value.name
          value       = env.value.value
          secret_name = env.value.secret_name
        }
      }
    }
  }

  tags = local.tags

  depends_on = [azurerm_role_assignment.api_acr_pull, azurerm_role_assignment.api_feedback_export_dedicated]

  lifecycle {
    # The deploy workflow sets the real image with `az containerapp job update` once az acr build
    # has pushed it (Story 7.1 notes): this stack creates the job with the same public placeholder
    # image the api Container App starts with, and never fights that out-of-band update (AD-11).
    ignore_changes = [
      template[0].container[0].image,
    ]
  }
}

# ---------------------------------------------------------------------------
# Monitoring (Story 1.5)
# ---------------------------------------------------------------------------
# PostgreSQL server logs to the workspace. The Container Apps environment needs no diagnostic
# setting: it already sends console and system logs there (logs_destination = log-analytics), and a
# second route would duplicate them (azure.md rule 15).
resource "azurerm_monitor_diagnostic_setting" "postgresql" {
  name                       = local.postgresql_diagnostic_setting_name
  target_resource_id         = module.postgresql_flexible_server.id
  log_analytics_workspace_id = module.log_analytics_workspace.id

  dynamic "enabled_log" {
    for_each = toset(local.postgresql_diagnostic_log_categories)

    content {
      category = enabled_log.value
    }
  }
}

# Hand-written azurerm: no Available AVM module for action groups is compatible with azurerm 5.x.
# Action groups are a global resource: Azure keeps no workload data in them, only the receivers.
resource "azurerm_monitor_action_group" "owner" {
  name                = local.names.action_group
  resource_group_name = module.resource_group.name
  short_name          = local.action_group_short_name

  dynamic "email_receiver" {
    for_each = toset(var.budget_alert_emails)

    content {
      name                    = "owner-${index(var.budget_alert_emails, email_receiver.value)}"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }

  tags = local.tags
}

# Hand-written azurerm: no Available AVM module for scheduled query rules is compatible with
# azurerm 5.x. Warns the owner when the last 24 hours' billable ingestion reaches 90% of the
# workspace's daily cap, before the cap stops ingestion (azure.md rule 18). Stateful (auto-mitigated),
# so it emails once per episode rather than every evaluation.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "log_cap" {
  name                    = local.names.log_cap_alert
  resource_group_name     = module.resource_group.name
  location                = var.location
  description             = "Billable Log Analytics ingestion over the last 24 hours has reached ${var.log_analytics_cap_alert_percent}% of the ${var.log_analytics_daily_quota_gb} GB daily cap."
  scopes                  = [module.log_analytics_workspace.id]
  severity                = 2
  evaluation_frequency    = "PT30M"
  window_duration         = "P1D"
  auto_mitigation_enabled = true

  criteria {
    query                   = local.log_cap_alert_query
    time_aggregation_method = "Maximum"
    metric_measure_column   = "BillableMB"
    operator                = "GreaterThanOrEqual"
    threshold               = local.log_cap_alert_threshold_mb

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.owner.id]
  }

  tags = local.tags
}

# Hand-written azurerm, same reasoning as log_cap above. Story 4.5, AC15: fires when an AI write's
# proposal differs from its turn's own proposal (cross-proposal write), or the write's turn id is
# unknown or already ended (a stale/replayed turn) -- either is a P0 isolation failure the app
# itself should never allow, so this is a second, independent guard on top of the turn-token checks
# (AD-4, AD-17, security.md rule 38). Stateful, so it emails once per episode.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "ai_write_isolation" {
  name                    = local.names.ai_write_isolation_alert
  resource_group_name     = module.resource_group.name
  location                = var.location
  description             = "An AI write's proposal differed from its turn's own proposal, or a write carried an unknown or already-ended turn ID."
  scopes                  = [module.log_analytics_workspace.id]
  severity                = 0
  evaluation_frequency    = "PT5M"
  window_duration         = local.ai_write_isolation_window
  auto_mitigation_enabled = true

  criteria {
    query                   = local.ai_write_isolation_query
    time_aggregation_method = "Maximum"
    metric_measure_column   = "SuspiciousWrites"
    operator                = "GreaterThan"
    threshold               = 0

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.owner.id]
  }

  tags = local.tags
}

# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
# Hand-written azurerm: there is no Available AVM module for consumption budgets (terraform.md rule 15).
# Budgets don't support tags.
resource "azurerm_consumption_budget_resource_group" "this" {
  name              = local.names.budget
  resource_group_id = module.resource_group.id
  amount            = var.budget_amount
  time_grain        = "Monthly"

  time_period {
    start_date = local.budget_start_date
  }

  dynamic "notification" {
    for_each = toset(var.budget_actual_thresholds)

    content {
      enabled        = true
      threshold      = notification.value
      threshold_type = "Actual"
      operator       = "GreaterThanOrEqualTo"
      contact_emails = var.budget_alert_emails
    }
  }

  dynamic "notification" {
    for_each = toset(var.budget_forecast_thresholds)

    content {
      enabled        = true
      threshold      = notification.value
      threshold_type = "Forecasted"
      operator       = "GreaterThanOrEqualTo"
      contact_emails = var.budget_alert_emails
    }
  }

  lifecycle {
    # timestamp() changes on every plan; the start date is fixed at creation (a change would replace the budget).
    ignore_changes = [time_period[0].start_date]
  }
}
