# demo environment values. No secrets here (terraform.md rule 24).

workload     = "sample"
env          = "demo"
region_short = "sea"
location     = "southeastasia"
owner        = "poc-owner"
repo_url     = "https://github.com/example-org/formapp"

log_analytics_retention_in_days = 30
log_analytics_daily_quota_gb    = 0.5
log_analytics_cap_alert_percent = 90

# Keep every api trace: demo traffic is low, and the workspace's daily cap bounds the cost.
telemetry_sampling_ratio = 1.0
# Raise to WARNING if logs push ingestion towards the cap (sampling affects traces only).
api_log_level = "INFO"

container_registry_sku = "Basic"

postgresql_version               = "18"
postgresql_sku_name              = "B_Standard_B1ms"
postgresql_storage_mb            = 32768
postgresql_backup_retention_days = 7

# Created by infra/bootstrap/state-backend.sh; paste the object ID it prints.
db_admin_group_name      = "formapp-db-admins"
db_admin_group_object_id = "11111111-1111-4111-8111-111111111111"

# Story 1.6: client ID of the hand-made single-tenant sign-in app registration (infra/README.md,
# Sign-in). Not a secret: sign-in uses ID tokens, so the registration has no client secret.
entra_signin_client_id = "22222222-2222-4222-8222-222222222222"

# Public placeholder until the pipeline deploys the api image; it listens on 8080, like the api image.
container_app_placeholder_image = "nginxinc/nginx-unprivileged:1.30.5-alpine@sha256:4714e0b1b2577eaa1a6131d07c958b67f0eb68e6d0521e90c6e5287db8cf0bc5"
container_app_target_port       = 8080
container_app_cpu               = 0.25
container_app_memory            = "0.5Gi"
container_app_min_replicas      = 1
container_app_max_replicas      = 1

turn_token_signing_key_rotation = "1"

# Story 4.1: Foundry account and the gpt-4.1-mini deployment (azure.md rules 19 and 24). Capacity is
# in thousands of tokens per minute; 30 is enough for a few demo turns at once.
foundry_sku_name       = "S0"
foundry_model_format   = "OpenAI"
foundry_model_name     = "gpt-4.1-mini"
foundry_model_version  = "2025-04-14"
foundry_model_sku_name = "GlobalStandard"
foundry_model_capacity = 30

# FORM-226 (owner decision, 2026-09-27): gpt-5.4-mini as a second deployment, and api and the
# hosted agent switched to it. gpt-4.1-mini (now Legacy, retiring 2027-04-14) stays deployed for
# rollback: set foundry_active_model_deployment back to "gpt-4.1-mini" to switch back. Removing it
# is a separate change, because the deploy's plan guard blocks destroying any Foundry resource.
foundry_next_model = {
  name     = "gpt-5.4-mini"
  format   = "OpenAI"
  model    = "gpt-5.4-mini"
  version  = "2026-03-17"
  sku_name = "GlobalStandard"
  capacity = 30
}
foundry_active_model_deployment = "gpt-5.4-mini"

# Story 6.1 (AD-19): dedicated Speech account for browser token minting.
speech_sku_name = "S0"

# Story 7.1/FORM-237 (AD-20): nightly feedback job. Same sizing as the api container; the job does
# almost nothing yet (Story 7.2/7.3 add the model call and the CSV write).
feedback_job_cpu                     = 0.25
feedback_job_memory                  = "0.5Gi"
feedback_job_replica_timeout_seconds = 900
feedback_job_replica_retry_limit     = 1
feedback_export_salt_rotation        = "1"

budget_amount              = 15
budget_alert_emails        = ["owner@example.com"]
budget_actual_thresholds   = [90, 100, 110]
budget_forecast_thresholds = [110]

# TEMPORARY (owner, 2026-09-26): PostgreSQL open to any IPv4 address until the owner says to close it.
# Set to false to close. Entra-only auth and verified TLS still apply.
postgresql_allow_public_access = true
