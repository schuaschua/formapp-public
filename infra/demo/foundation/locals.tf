locals {
  # <abbr>-<workload>-<env>-<region_short>[-<role>] (azure.md naming table). The only place names are built.
  name_suffix = "${var.workload}-${var.env}-${var.region_short}"

  names = {
    resource_group             = "rg-${local.name_suffix}"
    container_registry         = "cr${replace(local.name_suffix, "-", "")}"
    log_analytics_workspace    = "log-${local.name_suffix}"
    container_apps_environment = "cae-${local.name_suffix}"
    container_app              = "ca-${local.name_suffix}"
    postgresql_flexible_server = "pgsql-${local.name_suffix}"
    api_identity               = "id-${local.name_suffix}-api"
    budget                     = "budget-${var.workload}-${var.env}"
    application_insights       = "appi-${local.name_suffix}"
    action_group               = "ag-${local.name_suffix}"
    log_cap_alert              = "ar-${local.name_suffix}-log-cap"
    ai_write_isolation_alert   = "ar-${local.name_suffix}-ai-write-isolation"
    storage_account            = "st${replace(local.name_suffix, "-", "")}"
    # FORM-240: the feedback export's own storage account (below), so Power BI's per-account
    # credential test never lists the sign-in token store's container.
    feedback_export_storage_account = "st${var.workload}fb${var.env}${var.region_short}"
    foundry_account                 = "aif-${local.name_suffix}"
    foundry_project                 = "proj-${local.name_suffix}"
    speech_account                  = "cog-${local.name_suffix}"
    speech_identity                 = "id-${local.name_suffix}-speech"
    # Story 7.1/FORM-237 (AD-20): the nightly feedback job.
    container_apps_job = "caj-${local.name_suffix}-feedback"
  }

  # Story 4.1: names inside Foundry (not Azure resources in the azure.md naming table). The hosted
  # agent's name is also the path segment of its Responses endpoint.
  hosted_agent_name            = "${var.workload}-agent"
  foundry_capability_host_name = "agents"
  # "-project" keeps it apart from the old account-level connection of the plain name, which the
  # project also sees (deploy run 36284637820: "Resource already exists" at the project path).
  foundry_appinsights_connection    = "${local.names.application_insights}-project"
  foundry_model_deployment_name     = var.foundry_model_name
  foundry_diagnostic_setting_name   = "to-${local.names.log_analytics_workspace}"
  foundry_diagnostic_log_categories = ["Audit", "RequestResponse"]

  # Story 6.1 (AD-19): the recognition locale and synthesis voice the browser's Speech SDK uses,
  # fixed for this POC (Singapore English, to match the agent's own audience) rather than a tfvars
  # knob -- there is only ever the one demo environment.
  speech_locale = "en-SG"
  speech_voice  = "en-SG-LunaNeural"

  # Built-in role definition GUIDs, the same in every tenant. Foundry User was named Azure AI User
  # before the rename, so it is referenced by ID, never by display name.
  role_definition_guids = {
    foundry_user                 = "53ca6127-db72-4b80-b1b0-d745d6d5456d"
    monitoring_metrics_publisher = "3913510d-42f4-4e42-8a64-420c390055eb"
  }
  role_definition_ids = {
    for role, guid in local.role_definition_guids :
    role => "/subscriptions/${data.azurerm_client_config.current.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${guid}"
  }

  # Child-resource names (not in the azure.md naming table).
  postgresql_azure_services_firewall_rule_name = "allow-azure-services"
  postgresql_public_access_firewall_rule_name  = "allow-public-temporary"
  postgresql_diagnostic_setting_name           = "to-${local.names.log_analytics_workspace}"

  # Story 1.6: Container Apps sign-in (Easy Auth). The platform requires the name "current"; the
  # token store keeps each signed-in session in this private container.
  auth_config_name      = "current"
  token_store_container = "tokenstore"
  # Single-tenant sign-in: only this directory's users (Decisions, 2026-09-26).
  entra_signin_issuer = "https://login.microsoftonline.com/${data.azurerm_client_config.current.tenant_id}/v2.0"

  # An action group's short name (at most 12 characters) is the sender name in its emails.
  action_group_short_name = substr("${var.workload}-${var.env}", 0, 12)

  # Story 1.5: the owner is warned when billable ingestion over the last 24 hours reaches this share
  # of the Log Analytics daily cap (azure.md rule 18). Rolling, because the cap resets at the
  # workspace's own hour, not at midnight UTC. Usage reports Quantity in MB (1 GB = 1000 MB).
  log_cap_alert_threshold_mb = var.log_analytics_daily_quota_gb * 1000 * var.log_analytics_cap_alert_percent / 100
  log_cap_alert_query        = <<-KQL
    Usage
    | where TimeGenerated > ago(1d)
    | where IsBillable == true
    | summarize BillableMB = sum(Quantity)
  KQL

  # PostgreSQL server logs only (errors, connections); no metrics or other categories
  # (azure.md rule 15).
  postgresql_diagnostic_log_categories = ["PostgreSQLLogs"]

  # Story 4.5, AC15 (AD-4, AD-9, AD-17, security.md rule 38): api's stdout already reaches this
  # same Log Analytics workspace as ContainerAppConsoleLogs_CL (the Container Apps environment's
  # logs_destination = log-analytics, no separate diagnostic setting needed -- same reasoning as
  # the "Monitoring" comment above). adapters.chat.logging_events writes one JSON line per
  # turn-start/turn-end/ai-write with event/proposal_id/turn_id/conversation_id; this alert fires
  # when a write's own proposal_id differs from the proposal its turn actually started on
  # (cross-proposal write), or the write's turn_id never started, or its turn had already ended
  # before the write happened (an unknown or stale/ended turn). A normal write -- its own
  # turn_start's proposal_id matches and that turn hasn't ended yet -- matches neither and never
  # fires. 30 minutes comfortably covers a turn (whose own AI lock safety window is 5 minutes) on
  # both sides of the evaluation window's edge. The query window is 15 minutes longer than the
  # span whose writes are checked, so a write early in that span still finds its turn_start
  # (Azure limits the query's data to window_duration, so the lookback alone can't widen it).
  ai_write_isolation_window       = "PT45M"
  ai_write_isolation_lookback     = "45m"
  ai_write_isolation_write_window = "30m"
  ai_write_isolation_query        = <<-KQL
    let AppLogs = ContainerAppConsoleLogs_CL
    | where ContainerAppName_s == "${local.names.container_app}"
    | where TimeGenerated > ago(${local.ai_write_isolation_lookback})
    | extend Entry = parse_json(Log_s)
    | where isnotempty(Entry.event);
    let TurnStarts = AppLogs
    | where Entry.event == "turn_start"
    | project TurnId = tostring(Entry.turn_id), StartProposalId = tostring(Entry.proposal_id);
    let TurnEnds = AppLogs
    | where Entry.event == "turn_end"
    | project TurnId = tostring(Entry.turn_id), EndedAt = TimeGenerated;
    let Writes = AppLogs
    | where Entry.event == "ai_write"
    | where TimeGenerated > ago(${local.ai_write_isolation_write_window})
    | project WriteTime = TimeGenerated, TurnId = tostring(Entry.turn_id), WriteProposalId = tostring(Entry.proposal_id);
    Writes
    | join kind=leftouter TurnStarts on TurnId
    | join kind=leftouter TurnEnds on TurnId
    | extend CrossProposalWrite = isnotempty(StartProposalId) and WriteProposalId != StartProposalId
    | extend UnknownOrEndedTurn = isempty(StartProposalId) or (isnotempty(EndedAt) and EndedAt < WriteTime)
    | where CrossProposalWrite or UnknownOrEndedTurn
    | summarize SuspiciousWrites = count()
  KQL

  # First day of the month of the first apply. Azure rejects a budget start in an earlier month,
  # and the budget ignores later changes to it (see main.tf).
  budget_start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())

  # Names inside the Container App (not Azure resources).
  api_container_name              = "api"
  turn_token_signing_secret_name  = "turn-token-signing-key"
  turn_token_signing_env_var_name = "TURN_TOKEN_SIGNING_KEY"

  # Story 1.5: the Application Insights connection string reaches api only as a secret reference.
  appinsights_connection_string_secret_name  = "appinsights-connection-string"
  appinsights_connection_string_env_var_name = "APPLICATIONINSIGHTS_CONNECTION_STRING"

  # The application database, created in the manual pgaadauth step (infra/bootstrap/README.md 3.3).
  database_name           = "formapp"
  database_sslmode        = "verify-full"
  database_migration_role = "formapp_migrator"

  # The api container's environment (Stories 1.3, 1.5). The Container App ignores its env after
  # creation (Story 4.1), and the agent stack resends this list, through api_container, on every
  # deploy, adding the agent env. Plain values or secret names only, never a secret value.
  api_env = [
    { name = local.turn_token_signing_env_var_name, value = null, secret_name = local.turn_token_signing_secret_name },
    # api settings (Story 1.3): api signs in to PostgreSQL as its managed identity with an Entra
    # token, so there is no database password (AD-10).
    { name = "FORMAPP_DEPLOYMENT", value = var.env, secret_name = null },
    { name = "DATABASE_HOST", value = module.postgresql_flexible_server.fqdn, secret_name = null },
    { name = "DATABASE_NAME", value = local.database_name, secret_name = null },
    { name = "DATABASE_USER", value = module.api_identity.name, secret_name = null },
    { name = "AZURE_CLIENT_ID", value = module.api_identity.client_id, secret_name = null },
    # Verify PostgreSQL's certificate and host name before sending the Entra token (AD-10).
    { name = "DATABASE_SSLMODE", value = local.database_sslmode, secret_name = null },
    # The AD-17 migration role, under the name the deploy's migration step uses; readiness fails if
    # api is a member of it.
    { name = "DB_MIGRATION_ROLE", value = local.database_migration_role, secret_name = null },
    # Story 1.5: telemetry to Application Insights (off in api without the connection string),
    # sampled at this ratio (azure.md rule 16).
    { name = local.appinsights_connection_string_env_var_name, value = null, secret_name = local.appinsights_connection_string_secret_name },
    { name = "TELEMETRY_SAMPLING_RATIO", value = tostring(var.telemetry_sampling_ratio), secret_name = null },
    { name = "LOG_LEVEL", value = var.api_log_level, secret_name = null },
    # Story 6.1 (AD-19): api mints Speech tokens for the dedicated speech identity; none of this is
    # a secret (the resource id and endpoint are not sensitive, and the identity has only Cognitive
    # Services Speech User on this one account).
    { name = "SPEECH_REGION", value = var.location, secret_name = null },
    { name = "SPEECH_ENDPOINT", value = azurerm_cognitive_account.speech.endpoint, secret_name = null },
    { name = "SPEECH_RESOURCE_ID", value = azurerm_cognitive_account.speech.id, secret_name = null },
    { name = "SPEECH_IDENTITY_CLIENT_ID", value = module.speech_identity.client_id, secret_name = null },
    { name = "SPEECH_LOCALE", value = local.speech_locale, secret_name = null },
    { name = "SPEECH_VOICE", value = local.speech_voice, secret_name = null },
  ]

  # api container probes (Story 1.3). The readiness timeout leaves room for api's own 4-second
  # database check; the startup probe allows a minute for the process to come up.
  api_probes = {
    startup = {
      path                    = "/healthz"
      initial_delay           = 1
      interval_seconds        = 5
      timeout                 = 3
      failure_count_threshold = 12
    }
    readiness = {
      path                    = "/readyz"
      initial_delay           = 0
      interval_seconds        = 10
      timeout                 = 5
      failure_count_threshold = 3
      success_count_threshold = 1
    }
    liveness = {
      path                    = "/healthz"
      initial_delay           = 1
      interval_seconds        = 10
      timeout                 = 3
      failure_count_threshold = 3
    }
  }

  # Story 7.1/FORM-237 (AD-20): the nightly feedback job. FORM-240: feedback-export moved to its
  # own storage account (module.feedback_export_storage) -- Power BI records a Blob source by
  # account and, when saving credentials, test-lists every container in it, so a container-scoped
  # role on an account that also holds the sign-in token store made Power BI reject the
  # credentials. The old feedback-export container on module.token_store was removed (owner,
  # 2026-09-28).
  feedback_export_container         = "feedback-export"
  feedback_job_container_name       = "feedback-job"
  feedback_job_command              = ["python", "-m", "jobs.feedback"]
  feedback_job_cron                 = "0 18 * * *" # ~02:00 MYT (UTC+8)
  feedback_export_salt_secret_name  = "feedback-export-salt"
  feedback_export_salt_env_var_name = "FEEDBACK_EXPORT_SALT"

  # The job's environment: the same DB and Foundry settings api uses, plus the export container
  # URL and the salt secret. Unlike api's own copies of the three FOUNDRY_* values (set only by
  # the agent stack's PATCH, because that stack owns api's whole env list end-to-end), the job
  # gets them straight from this stack's own module.foundry and hosted_agent_name -- it has no
  # second Terraform stack, so it needs no dependency on infra/demo/agent (AD-20 binds this story
  # to infra/demo/foundation only).
  feedback_job_env = [
    { name = "FORMAPP_DEPLOYMENT", value = var.env, secret_name = null },
    { name = "DATABASE_HOST", value = module.postgresql_flexible_server.fqdn, secret_name = null },
    { name = "DATABASE_NAME", value = local.database_name, secret_name = null },
    { name = "DATABASE_USER", value = module.api_identity.name, secret_name = null },
    { name = "AZURE_CLIENT_ID", value = module.api_identity.client_id, secret_name = null },
    { name = "DATABASE_SSLMODE", value = local.database_sslmode, secret_name = null },
    { name = "FOUNDRY_PROJECT_ENDPOINT", value = module.foundry.project_endpoint, secret_name = null },
    { name = "FOUNDRY_AGENT_NAME", value = local.hosted_agent_name, secret_name = null },
    { name = "FOUNDRY_MODEL", value = module.foundry.model_deployment_name, secret_name = null },
    {
      name        = "FEEDBACK_EXPORT_CONTAINER_URL"
      value       = module.feedback_export_storage.container_urls[local.feedback_export_container]
      secret_name = null
    },
    { name = local.feedback_export_salt_env_var_name, value = null, secret_name = local.feedback_export_salt_secret_name },
    { name = "LOG_LEVEL", value = var.api_log_level, secret_name = null },
  ]

  # The six required tags (azure.md), passed to every taggable resource.
  tags = {
    workload  = var.workload
    env       = var.env
    owner     = var.owner
    managedby = "terraform"
    datatype  = "synthetic"
    repo      = var.repo_url
  }
}
