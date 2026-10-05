# Sets the Container App's api image to the commit the deploy workflow built (AD-11), and, once
# foundation has the Foundry resources (Story 4.1), adds the agent env for api.
#
# The containers array is replaced as a whole, so foundation's api_container spec (name, sizing,
# probes, env with secret names only) is resent with the new image; foundation stays the owner of
# env, probes and sizing, and ignores the env and image on the Container App itself.
#
# azapi_resource_action with PATCH, not azapi_update_resource: azapi_update_resource always sends a
# PUT built from a GET, and Container Apps never returns secret values on GET, so that PUT fails with
# ContainerAppSecretInvalid (Azure/terraform-provider-azapi#542). PATCH (JSON merge patch) touches
# only properties.template.containers and leaves secrets, ingress and scale as foundation set them.
resource "azapi_resource_action" "api_image" {
  count = local.foundation_ready ? 1 : 0

  type        = "Microsoft.App/containerApps@2026-01-01"
  resource_id = local.foundation.container_app_id
  method      = "PATCH"

  body = {
    properties = {
      template = {
        containers = [merge(local.foundation.api_container, {
          image = local.api_image
          env   = concat(local.foundation.api_container.env, local.api_agent_env)
        })]
      }
    }
  }
}

# ---------------------------------------------------------------------------
# Hosted agent (Story 4.1)
# ---------------------------------------------------------------------------
# azapi_data_plane_resource: azurerm has no resource for Foundry hosted agents (terraform.md rule 12).
# Microsoft.Foundry/agents@v1 creates the agent with POST {project endpoint}/agents and a new version
# on each change of the definition. Field names from Microsoft Learn, "Deploy a hosted agent" (REST:
# kind, container_configuration.image, cpu, memory, protocol_versions, environment_variables) and
# "Manage hosted agent sessions" (session_configuration.idle_timeout_seconds, 120-3600, default 900);
# the parent is the project endpoint without its scheme, as in the azapi Microsoft.Foundry/agents
# example (JFolberth/simple-hosted-agent-deploy-azapi). No rai_config: the model deployment's
# default content filter applies (azure.md rule 25).
resource "azapi_data_plane_resource" "hosted_agent" {
  count = local.foundry_ready ? 1 : 0

  type      = "Microsoft.Foundry/agents@v1"
  parent_id = trimprefix(local.foundation.foundry_project_endpoint, "https://")
  name      = local.foundation.hosted_agent_name

  body = {
    name = local.foundation.hosted_agent_name
    definition = {
      kind = "hosted"
      container_configuration = {
        image = local.agent_image
      }
      # AD-9 and azure.md rule 20: 0.5 vCPU / 1 GiB, compute released after 15 idle minutes.
      cpu    = var.agent_cpu
      memory = var.agent_memory
      protocol_versions = [
        { protocol = "responses", version = local.responses_protocol_version },
      ]
      environment_variables = local.agent_env
      session_configuration = {
        idle_timeout_seconds = var.agent_idle_timeout_seconds
      }
    }
  }

  # The agent's own Entra identity (Microsoft Foundry REST reference, agent object:
  # instance_identity.principal_id). The container runs as it; the project identity only pulls
  # the image.
  response_export_values = {
    principal_id = "instance_identity.principal_id"
  }
}

# The hosted agent's roles (azure.md rule 9): Foundry User on the project and Monitoring Metrics
# Publisher on Application Insights (telemetry with Entra auth; local auth is off). Scopes and role
# IDs come from foundation; the identity exists only once the agent does, so they are assigned here.
# azapi, not azurerm: this stack has only the azapi provider. principalType is ServicePrincipal,
# which the pipeline's RBAC Administrator condition requires.
resource "azapi_resource" "hosted_agent_role" {
  for_each = local.foundry_ready ? local.foundation.hosted_agent_role_assignments : {}

  type      = "Microsoft.Authorization/roleAssignments@2022-04-01"
  name      = uuidv5("url", "${each.value.scope}|${azapi_data_plane_resource.hosted_agent[0].output.principal_id}|${each.value.role_definition_id}")
  parent_id = each.value.scope

  body = {
    properties = {
      principalId      = azapi_data_plane_resource.hosted_agent[0].output.principal_id
      principalType    = "ServicePrincipal"
      roleDefinitionId = each.value.role_definition_id
    }
  }
}
