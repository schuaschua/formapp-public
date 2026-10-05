variable "workload" {
  description = "Workload name used in resource names and the workload tag."
  type        = string
}

variable "env" {
  description = "Environment name used in resource names and the env tag."
  type        = string
}

variable "region_short" {
  description = "Short region code used in resource names (sea = Southeast Asia)."
  type        = string
}

variable "location" {
  description = "Azure region for every resource."
  type        = string
  default     = "southeastasia"

  validation {
    condition     = var.location == "southeastasia"
    error_message = "All formapp resources must be in southeastasia (azure.md rule 5)."
  }
}

variable "owner" {
  description = "Alias of the responsible person, used for the owner tag (no personal data)."
  type        = string
}

variable "repo_url" {
  description = "URL of the source repository, used for the repo tag."
  type        = string
}

variable "log_analytics_retention_in_days" {
  description = "Log Analytics data retention in days."
  type        = number
}

variable "log_analytics_daily_quota_gb" {
  description = "Log Analytics daily ingestion cap in GB."
  type        = number

  validation {
    condition     = var.log_analytics_daily_quota_gb > 0
    error_message = "log_analytics_daily_quota_gb must be above 0 (the cap alert is a share of it)."
  }
}

variable "log_analytics_cap_alert_percent" {
  description = "Share of the Log Analytics daily cap, in percent, at which the owner is alerted."
  type        = number

  validation {
    condition     = var.log_analytics_cap_alert_percent > 0 && var.log_analytics_cap_alert_percent <= 100
    error_message = "log_analytics_cap_alert_percent must be above 0 and at most 100."
  }
}

variable "telemetry_sampling_ratio" {
  description = "Share of api traces kept, from 0 (none) to 1 (all), passed to api as TELEMETRY_SAMPLING_RATIO (azure.md rule 16)."
  type        = number

  validation {
    condition     = var.telemetry_sampling_ratio >= 0 && var.telemetry_sampling_ratio <= 1
    error_message = "telemetry_sampling_ratio must be between 0 and 1."
  }
}

variable "api_log_level" {
  description = "Lowest level api writes to stdout (ContainerAppConsoleLogs), passed as LOG_LEVEL."
  type        = string

  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], var.api_log_level)
    error_message = "api_log_level must be DEBUG, INFO, WARNING, ERROR or CRITICAL."
  }
}

variable "container_registry_sku" {
  description = "Container registry SKU."
  type        = string
}

variable "postgresql_version" {
  description = "PostgreSQL major version."
  type        = string
}

variable "postgresql_sku_name" {
  description = "PostgreSQL compute SKU (Burstable)."
  type        = string
}

variable "postgresql_storage_mb" {
  description = "PostgreSQL storage in MB (smallest size; it can't be scaled down)."
  type        = number
}

variable "postgresql_backup_retention_days" {
  description = "PostgreSQL point-in-time restore window in days."
  type        = number
}

variable "db_admin_group_name" {
  description = "Display name of the Entra group that administers PostgreSQL (created by the bootstrap script)."
  type        = string
}

variable "db_admin_group_object_id" {
  description = "Object ID of the Entra group that administers PostgreSQL (printed by the bootstrap script)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.db_admin_group_object_id)) && var.db_admin_group_object_id != "00000000-0000-0000-0000-000000000000"
    error_message = "Set db_admin_group_object_id in terraform.tfvars to the object ID printed by infra/bootstrap/state-backend.sh."
  }
}

variable "entra_signin_client_id" {
  description = "Client (application) ID of the hand-made Entra app registration for sign-in (infra/README.md, Sign-in). Not a secret; there is no client secret."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.entra_signin_client_id)) && var.entra_signin_client_id != "00000000-0000-0000-0000-000000000000"
    error_message = "Set entra_signin_client_id in terraform.tfvars to the app registration's client ID (infra/README.md, Sign-in)."
  }
}

variable "container_app_placeholder_image" {
  description = "Public placeholder image used when the Container App is first created; later images come from the agent stack."
  type        = string
}

variable "container_app_target_port" {
  description = "Port the api container listens on behind HTTPS ingress."
  type        = number
}

variable "container_app_cpu" {
  description = "vCPU for the api container."
  type        = number
}

variable "container_app_memory" {
  description = "Memory for the api container (e.g. 0.5Gi)."
  type        = string
}

variable "container_app_min_replicas" {
  description = "Minimum replica count of the Container App."
  type        = number
}

variable "container_app_max_replicas" {
  description = "Maximum replica count of the Container App."
  type        = number
}

variable "turn_token_signing_key_rotation" {
  description = "Change this value to rotate the turn-token signing key on the next apply (security.md rule 12)."
  type        = string
}

variable "budget_amount" {
  description = "Monthly budget for the resource group, in the billing currency."
  type        = number
}

variable "budget_alert_emails" {
  description = "Email addresses that receive the budget alerts and the monitoring alerts (action group)."
  type        = list(string)

  validation {
    condition     = length(var.budget_alert_emails) > 0
    error_message = "budget_alert_emails needs at least one address, or no alert reaches anyone."
  }
}

variable "budget_actual_thresholds" {
  description = "Actual-cost alert thresholds, in percent of the budget."
  type        = list(number)
}

variable "budget_forecast_thresholds" {
  description = "Forecasted-cost alert thresholds, in percent of the budget."
  type        = list(number)
}

variable "postgresql_allow_public_access" {
  description = "TEMPORARY owner-approved exception (azure.md rule 13): open PostgreSQL to any IPv4 address; the deploy then skips its per-run firewall rule. Set to false to close."
  type        = bool
  default     = false
}

variable "foundry_sku_name" {
  description = "SKU of the Foundry account (S0 is the only AIServices tier)."
  type        = string
}

variable "foundry_model_format" {
  description = "Publisher format of the model deployment (OpenAI)."
  type        = string
}

variable "foundry_model_name" {
  description = "Model of the deployment; also the deployment name that reaches api as FOUNDRY_MODEL and the hosted agent as MODEL_DEPLOYMENT_NAME (FOUNDRY_MODEL is reserved for platform use in the hosted agent container)."
  type        = string
}

variable "foundry_model_version" {
  description = "Pinned model version (azure.md rule 24); plan the swap before it retires."
  type        = string
}

variable "foundry_model_sku_name" {
  description = "Deployment type of the model (Global Standard pay-per-token, azure.md rule 19)."
  type        = string
}

variable "foundry_model_capacity" {
  description = "Model deployment capacity in thousands of tokens per minute (kept low, azure.md rule 19)."
  type        = number
}

variable "foundry_next_model" {
  description = "Optional second model deployment on the Foundry account (FORM-226), so the model can be switched without replacing the first. Its name is what reaches code when it is the active deployment. Null for none."
  type = object({
    name     = string
    format   = string
    model    = string
    version  = string
    sku_name = string
    capacity = number
  })
  default = null
}

variable "foundry_active_model_deployment" {
  description = "Deployment name api (FOUNDRY_MODEL) and the hosted agent (MODEL_DEPLOYMENT_NAME) use: foundry_model_name or foundry_next_model.name. Null means foundry_model_name."
  type        = string
  default     = null
}

variable "speech_sku_name" {
  description = "SKU of the Speech account (S0 is the cheapest tier that supports Entra/local_auth_enabled=false)."
  type        = string
}

variable "feedback_job_cpu" {
  description = "vCPU for the nightly feedback job container (Story 7.1/FORM-237)."
  type        = number
}

variable "feedback_job_memory" {
  description = "Memory for the nightly feedback job container (e.g. 0.5Gi)."
  type        = string
}

variable "feedback_job_replica_timeout_seconds" {
  description = "Seconds a feedback job replica may run before Container Apps stops it."
  type        = number
}

variable "feedback_job_replica_retry_limit" {
  description = "Retries for a failed feedback job replica before Container Apps gives up."
  type        = number
}

variable "feedback_export_salt_rotation" {
  description = "Change this value to rotate the feedback-export agent hash salt on the next apply (security.md rule 12)."
  type        = string
}
