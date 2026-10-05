output "resource_group_name" {
  description = "Name of the demo resource group."
  value       = module.resource_group.name
}

output "container_registry_login_server" {
  description = "Login server of the registry that az acr build pushes to and the agent stack pulls from."
  value       = module.container_registry.login_server
}

output "container_app_id" {
  description = "Resource ID of the Container App, patched by the agent stack with azapi_resource_action (PATCH)."
  value       = azurerm_container_app.api.id
}

output "container_app_name" {
  description = "Name of the Container App."
  value       = azurerm_container_app.api.name
}

output "container_app_fqdn" {
  description = "Public FQDN of the Container App ingress (used by the smoke check)."
  value       = azurerm_container_app.api.ingress[0].fqdn
}

output "postgresql_server_name" {
  description = "Name of the PostgreSQL flexible server (for the migration step's temporary firewall rule)."
  value       = module.postgresql_flexible_server.name
}

output "postgresql_fqdn" {
  description = "FQDN of the PostgreSQL flexible server."
  value       = module.postgresql_flexible_server.fqdn
}

output "api_identity_name" {
  description = "Name of the api managed identity (its PostgreSQL principal name)."
  value       = module.api_identity.name
}

output "api_identity_client_id" {
  description = "Client ID of the api managed identity."
  value       = module.api_identity.client_id
}

output "container_registry_name" {
  description = "Name of the registry, for az acr build in the deploy workflow."
  value       = module.container_registry.name
}

# The agent stack patches the image with azapi_resource_action (PATCH), which replaces the whole
# properties.template.containers array, so it resends this spec with the new image and foundation
# stays the only owner of the container's env and sizing (AD-11). ARM (Microsoft.App/containerApps)
# shape, without the image. Env entries carry a secretRef (the secret's name) or a plain value,
# never a secret value. The probes travel here too, or every deploy would drop them.
output "api_container" {
  description = "The api container spec (ARM shape, no image, secret names only, with env and probes) that the agent stack resends with the new image."
  value = {
    name = azurerm_container_app.api.template[0].container[0].name
    resources = {
      cpu    = azurerm_container_app.api.template[0].container[0].cpu
      memory = azurerm_container_app.api.template[0].container[0].memory
    }
    # From local.api_env, not from the resource: the Container App ignores env changes after creation
    # (Story 4.1), so the list in code is the source of truth. Each entry keeps only its set keys:
    # name plus secretRef or value (ARM rejects both, or nulls).
    env = [
      for e in local.api_env : {
        for key, value in { name = e.name, secretRef = e.secret_name, value = e.value } : key => value
        if value != null && value != ""
      }
    ]
    probes = concat(
      [
        for p in azurerm_container_app.api.template[0].container[0].startup_probe : {
          type                = "Startup"
          httpGet             = { path = p.path, port = p.port, scheme = p.transport }
          initialDelaySeconds = p.initial_delay
          periodSeconds       = p.interval_seconds
          timeoutSeconds      = p.timeout
          failureThreshold    = p.failure_count_threshold
        }
      ],
      [
        for p in azurerm_container_app.api.template[0].container[0].readiness_probe : {
          type                = "Readiness"
          httpGet             = { path = p.path, port = p.port, scheme = p.transport }
          initialDelaySeconds = p.initial_delay
          periodSeconds       = p.interval_seconds
          timeoutSeconds      = p.timeout
          failureThreshold    = p.failure_count_threshold
          successThreshold    = p.success_count_threshold
        }
      ],
      [
        for p in azurerm_container_app.api.template[0].container[0].liveness_probe : {
          type                = "Liveness"
          httpGet             = { path = p.path, port = p.port, scheme = p.transport }
          initialDelaySeconds = p.initial_delay
          periodSeconds       = p.interval_seconds
          timeoutSeconds      = p.timeout
          failureThreshold    = p.failure_count_threshold
        }
      ],
    )
  }
}

output "postgresql_public_access" {
  description = "Whether the temporary allow-all PostgreSQL firewall rule is on (the deploy skips its per-run runner rule when true)."
  value       = var.postgresql_allow_public_access
}

# ---------------------------------------------------------------------------
# Story 7.1/FORM-237: what the deploy workflow needs to set the feedback job's image
# ---------------------------------------------------------------------------
output "container_app_job_id" {
  description = "Resource ID of the nightly feedback job."
  value       = azurerm_container_app_job.feedback.id
}

output "container_app_job_name" {
  description = "Name of the nightly feedback job, for the deploy workflow's `az containerapp job update --image` step."
  value       = azurerm_container_app_job.feedback.name
}

# ---------------------------------------------------------------------------
# Story 4.1: what the agent stack needs for the hosted agent (no keys or connection strings)
# ---------------------------------------------------------------------------
output "foundry_project_endpoint" {
  description = "Foundry project endpoint: the hosted agent's parent, and FOUNDRY_PROJECT_ENDPOINT for api. The platform injects FOUNDRY_PROJECT_ENDPOINT into the hosted agent container itself, so the agent stack never sets it there."
  value       = module.foundry.project_endpoint
}

output "model_deployment_name" {
  description = "Model deployment name, passed to api as FOUNDRY_MODEL and to the hosted agent as MODEL_DEPLOYMENT_NAME (FOUNDRY_MODEL is reserved for platform use in the hosted agent container); never written in code."
  value       = module.foundry.model_deployment_name
}

output "hosted_agent_name" {
  description = "Name of the hosted agent the agent stack creates; api calls it as FOUNDRY_AGENT_NAME."
  value       = local.hosted_agent_name
}

# The hosted agent runs as its own Entra agent identity, which exists only once the agent stack has
# created the agent; that stack assigns these roles to it (azure.md rule 9).
output "hosted_agent_role_assignments" {
  description = "Roles for the hosted agent's identity, by key: the scope and the role definition ID (Foundry User on the project, Monitoring Metrics Publisher on Application Insights)."
  value = {
    foundry_user = {
      scope              = module.foundry.project_id
      role_definition_id = local.role_definition_ids.foundry_user
    }
    monitoring_metrics_publisher = {
      scope              = module.application_insights.id
      role_definition_id = local.role_definition_ids.monitoring_metrics_publisher
    }
  }
}
