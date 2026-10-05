locals {
  foundation = data.terraform_remote_state.foundation.outputs

  # Before foundation's first apply (or before it publishes api_container), its state has none of
  # these outputs; the stack then plans nothing instead of failing.
  foundation_ready = alltrue([
    for name in ["container_app_id", "container_registry_login_server", "api_container"] :
    can(local.foundation[name])
  ])

  # Story 4.1: the second gate. Until foundation has applied the Foundry resources, the stack only
  # patches the api image, as before: no hosted agent and no agent env.
  foundry_ready = local.foundation_ready && alltrue([
    for name in ["container_app_fqdn", "foundry_project_endpoint", "model_deployment_name", "hosted_agent_name", "hosted_agent_role_assignments"] :
    can(local.foundation[name])
  ])

  api_image   = local.foundation_ready ? "${local.foundation.container_registry_login_server}/${var.image_repository}:${var.image_tag}" : null
  agent_image = local.foundry_ready ? "${local.foundation.container_registry_login_server}/${var.agent_image_repository}:${var.image_tag}" : null

  # The hosted agent's settings (Story 4.2's names, agent/formapp_agent/settings.py). FOUNDRY_* and
  # AGENT_* names are reserved for platform use and rejected here (400 invalid_payload; Microsoft
  # Learn, "Deploy a hosted agent" and "Configure environment variables for a hosted agent"): the
  # platform injects FOUNDRY_PROJECT_ENDPOINT and APPLICATIONINSIGHTS_CONNECTION_STRING itself, so
  # neither is set here, and the model deployment name goes in as MODEL_DEPLOYMENT_NAME instead of
  # the reserved FOUNDRY_MODEL. AZURE_CLIENT_ID and LOG_LEVEL stay unset (the platform identity, INFO).
  agent_env = local.foundry_ready ? {
    FORMAPP_MCP_URL          = "https://${local.foundation.container_app_fqdn}/mcp"
    MODEL_DEPLOYMENT_NAME    = local.foundation.model_deployment_name
    TELEMETRY_SAMPLING_RATIO = tostring(var.telemetry_sampling_ratio)
  } : {}

  # What api needs to call the hosted agent (Story 4.5), appended to foundation's env in the PATCH.
  api_agent_env = local.foundry_ready ? [
    { name = "FOUNDRY_PROJECT_ENDPOINT", value = local.foundation.foundry_project_endpoint },
    { name = "FOUNDRY_AGENT_NAME", value = local.foundation.hosted_agent_name },
    { name = "FOUNDRY_MODEL", value = local.foundation.model_deployment_name },
  ] : []

  # The Responses protocol version the hosting package serves (Microsoft Learn, "Deploy a hosted
  # agent": protocol_versions [{protocol = "responses", version = "2.0.0"}]).
  responses_protocol_version = "2.0.0"
}
