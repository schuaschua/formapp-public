# Plan-only tests with a mock provider and overridden remote state: no Azure access, no state.
# Run: terraform init -backend=false && terraform test

mock_provider "azapi" {}

variables {
  image_tag = "abc1234"
}

run "before_first_foundation_apply_plans_nothing" {
  command = plan

  override_data {
    target = data.terraform_remote_state.foundation
    values = {
      outputs = {}
    }
  }

  assert {
    condition     = length(azapi_resource_action.api_image) == 0
    error_message = "With no foundation outputs, the agent stack must plan no change."
  }

  assert {
    condition     = output.api_image == null
    error_message = "api_image must be null before foundation is applied."
  }
}

run "foundation_without_api_container_plans_nothing" {
  command = plan

  override_data {
    target = data.terraform_remote_state.foundation
    values = {
      outputs = {
        container_app_id                = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.App/containerApps/ca-sample-demo-sea"
        container_registry_login_server = "crsampledemosea.azurecr.io"
      }
    }
  }

  assert {
    condition     = length(azapi_resource_action.api_image) == 0
    error_message = "Without the api_container output, the agent stack must plan no change."
  }
}

run "patches_the_image_and_resends_the_container_spec" {
  command = plan

  override_data {
    target = data.terraform_remote_state.foundation
    values = {
      outputs = {
        container_app_id                = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.App/containerApps/ca-sample-demo-sea"
        container_registry_login_server = "crsampledemosea.azurecr.io"
        api_container = {
          name      = "api"
          resources = { cpu = 0.25, memory = "0.5Gi" }
          env = [
            { name = "TURN_TOKEN_SIGNING_KEY", secretRef = "turn-token-signing-key" },
            { name = "DATABASE_HOST", value = "pgsql-sample-demo-sea.postgres.database.azure.com" },
          ]
          probes = [
            { type = "Startup", httpGet = { path = "/healthz", port = 8080, scheme = "HTTP" }, periodSeconds = 5 },
            { type = "Readiness", httpGet = { path = "/readyz", port = 8080, scheme = "HTTP" }, periodSeconds = 10 },
            { type = "Liveness", httpGet = { path = "/healthz", port = 8080, scheme = "HTTP" }, periodSeconds = 10 },
          ]
        }
      }
    }
  }

  assert {
    condition     = length(azapi_resource_action.api_image) == 1
    error_message = "With foundation outputs, the agent stack must patch the Container App."
  }

  assert {
    condition     = azapi_resource_action.api_image[0].method == "PATCH"
    error_message = "The image must be set with PATCH (a PUT would drop the Container App's secrets)."
  }

  assert {
    condition     = azapi_resource_action.api_image[0].resource_id == "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.App/containerApps/ca-sample-demo-sea"
    error_message = "The patch must target foundation's Container App."
  }

  assert {
    condition = jsonencode(azapi_resource_action.api_image[0].body) == jsonencode({
      properties = {
        template = {
          containers = [{
            env = [
              { name = "TURN_TOKEN_SIGNING_KEY", secretRef = "turn-token-signing-key" },
              { name = "DATABASE_HOST", value = "pgsql-sample-demo-sea.postgres.database.azure.com" },
            ]
            image = "crsampledemosea.azurecr.io/api:abc1234"
            name  = "api"
            probes = [
              { type = "Startup", httpGet = { path = "/healthz", port = 8080, scheme = "HTTP" }, periodSeconds = 5 },
              { type = "Readiness", httpGet = { path = "/readyz", port = 8080, scheme = "HTTP" }, periodSeconds = 10 },
              { type = "Liveness", httpGet = { path = "/healthz", port = 8080, scheme = "HTTP" }, periodSeconds = 10 },
            ]
            resources = { cpu = 0.25, memory = "0.5Gi" }
          }]
        }
      }
    })
    error_message = "The patch must resend foundation's container spec (env and probes included) with only the image added."
  }

  assert {
    condition     = output.api_image == "crsampledemosea.azurecr.io/api:abc1234"
    error_message = "api_image must be <login server>/api:<image_tag>."
  }
}

run "rejects_an_invalid_image_tag" {
  command = plan

  override_data {
    target = data.terraform_remote_state.foundation
    values = {
      outputs = {}
    }
  }

  variables {
    image_tag = "not a tag"
  }

  expect_failures = [var.image_tag]
}

# ---------------------------------------------------------------------------
# Story 4.1: the hosted agent and the agent env
# ---------------------------------------------------------------------------
run "story_4_1_without_foundry_outputs_only_the_image_is_patched" {
  command = plan

  override_data {
    target = data.terraform_remote_state.foundation
    values = {
      outputs = {
        container_app_id                = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.App/containerApps/ca-sample-demo-sea"
        container_app_fqdn              = "ca-sample-demo-sea.example.southeastasia.azurecontainerapps.io"
        container_registry_login_server = "crsampledemosea.azurecr.io"
        api_container = {
          name      = "api"
          resources = { cpu = 0.25, memory = "0.5Gi" }
          env       = [{ name = "DATABASE_NAME", value = "formapp" }]
          probes    = []
        }
      }
    }
  }

  assert {
    condition     = length(azapi_resource_action.api_image) == 1
    error_message = "Without the Foundry outputs, the api image must still be patched."
  }

  assert {
    condition     = length(azapi_data_plane_resource.hosted_agent) == 0 && length(azapi_resource.hosted_agent_role) == 0
    error_message = "Without the Foundry outputs, no hosted agent and no agent roles may be planned."
  }

  assert {
    condition     = jsonencode(azapi_resource_action.api_image[0].body.properties.template.containers[0].env) == jsonencode([{ name = "DATABASE_NAME", value = "formapp" }])
    error_message = "Without the Foundry outputs, the PATCH must carry foundation's env only (no agent env)."
  }

  assert {
    condition     = output.agent_image == null && output.hosted_agent_name == null
    error_message = "agent_image and hosted_agent_name must be null before Foundry exists."
  }
}

run "story_4_1_creates_the_hosted_agent_version" {
  command = plan

  override_data {
    target = data.terraform_remote_state.foundation
    values = {
      outputs = {
        container_app_id                = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.App/containerApps/ca-sample-demo-sea"
        container_app_fqdn              = "ca-sample-demo-sea.example.southeastasia.azurecontainerapps.io"
        container_registry_login_server = "crsampledemosea.azurecr.io"
        api_container = {
          name      = "api"
          resources = { cpu = 0.25, memory = "0.5Gi" }
          env = [
            { name = "TURN_TOKEN_SIGNING_KEY", secretRef = "turn-token-signing-key" },
            { name = "DATABASE_NAME", value = "formapp" },
          ]
          probes = []
        }
        foundry_project_endpoint = "https://aif-sample-demo-sea.services.ai.azure.com/api/projects/proj-sample-demo-sea"
        model_deployment_name    = "gpt-4.1-mini"
        hosted_agent_name        = "formapp-agent"
        hosted_agent_role_assignments = {
          foundry_user = {
            scope              = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/aif-sample-demo-sea/projects/proj-sample-demo-sea"
            role_definition_id = "/subscriptions/00000000-0000-0000-0000-00000000000b/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
          }
          monitoring_metrics_publisher = {
            scope              = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/components/appi-sample-demo-sea"
            role_definition_id = "/subscriptions/00000000-0000-0000-0000-00000000000b/providers/Microsoft.Authorization/roleDefinitions/3913510d-42f4-4e42-8a64-420c390055eb"
          }
        }
      }
    }
  }

  # A known agent identity, so the role assignments can be checked at plan time.
  override_resource {
    target          = azapi_data_plane_resource.hosted_agent
    override_during = plan
    values = {
      output = { principal_id = "00000000-0000-0000-0000-0000000000f1" }
    }
  }

  assert {
    condition = (
      azapi_data_plane_resource.hosted_agent[0].type == "Microsoft.Foundry/agents@v1"
      && azapi_data_plane_resource.hosted_agent[0].parent_id == "aif-sample-demo-sea.services.ai.azure.com/api/projects/proj-sample-demo-sea"
      && azapi_data_plane_resource.hosted_agent[0].name == "formapp-agent"
    )
    error_message = "The hosted agent must be Microsoft.Foundry/agents@v1 formapp-agent under the project endpoint (without https://)."
  }

  assert {
    condition = jsonencode(azapi_data_plane_resource.hosted_agent[0].body) == jsonencode({
      definition = {
        container_configuration = { image = "crsampledemosea.azurecr.io/agent:abc1234" }
        cpu                     = "0.5"
        environment_variables = {
          FORMAPP_MCP_URL          = "https://ca-sample-demo-sea.example.southeastasia.azurecontainerapps.io/mcp"
          MODEL_DEPLOYMENT_NAME    = "gpt-4.1-mini"
          TELEMETRY_SAMPLING_RATIO = "1"
        }
        kind                  = "hosted"
        memory                = "1Gi"
        protocol_versions     = [{ protocol = "responses", version = "2.0.0" }]
        session_configuration = { idle_timeout_seconds = 900 }
      }
      name = "formapp-agent"
    })
    error_message = "The hosted agent must run agent:<SHA> at 0.5 vCPU / 1 GiB, 15-minute idle, Responses 2.0.0, with the MCP URL, model deployment name and sampling ratio as env (never FOUNDRY_PROJECT_ENDPOINT: the platform injects it)."
  }

  assert {
    condition     = !contains(keys(azapi_data_plane_resource.hosted_agent[0].body.definition.environment_variables), "APPLICATIONINSIGHTS_CONNECTION_STRING")
    error_message = "The App Insights connection string is injected by the platform, never set by Terraform."
  }

  assert {
    condition = alltrue([
      for key in keys(azapi_data_plane_resource.hosted_agent[0].body.definition.environment_variables) :
      !can(regex("^(FOUNDRY_|AGENT_)", key))
    ])
    error_message = "No hosted-agent environment variable may start with FOUNDRY_ or AGENT_: the platform reserves both prefixes and rejects the version create (400 invalid_payload) if one is declared."
  }

  assert {
    condition     = !contains(keys(azapi_data_plane_resource.hosted_agent[0].body.definition), "rai_config")
    error_message = "No custom RAI policy: the deployment's default content filter applies (azure.md rule 25)."
  }

  assert {
    condition = jsonencode(azapi_resource_action.api_image[0].body.properties.template.containers[0].env) == jsonencode([
      { name = "TURN_TOKEN_SIGNING_KEY", secretRef = "turn-token-signing-key" },
      { name = "DATABASE_NAME", value = "formapp" },
      { name = "FOUNDRY_PROJECT_ENDPOINT", value = "https://aif-sample-demo-sea.services.ai.azure.com/api/projects/proj-sample-demo-sea" },
      { name = "FOUNDRY_AGENT_NAME", value = "formapp-agent" },
      { name = "FOUNDRY_MODEL", value = "gpt-4.1-mini" },
    ])
    error_message = "The PATCH must resend foundation's env and append the api agent env."
  }

  assert {
    condition     = azapi_resource_action.api_image[0].body.properties.template.containers[0].image == "crsampledemosea.azurecr.io/api:abc1234"
    error_message = "The api image must still be patched."
  }

  assert {
    condition     = output.agent_image == "crsampledemosea.azurecr.io/agent:abc1234" && output.hosted_agent_name == "formapp-agent"
    error_message = "agent_image must be <login server>/agent:<image_tag>, and hosted_agent_name the agent's name."
  }

  assert {
    condition = toset([for r in azapi_resource.hosted_agent_role : jsonencode({
      scope = r.parent_id, role = r.body.properties.roleDefinitionId, principal = r.body.properties.principalId, type = r.body.properties.principalType
      })]) == toset([
      jsonencode({
        scope     = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/aif-sample-demo-sea/projects/proj-sample-demo-sea"
        role      = "/subscriptions/00000000-0000-0000-0000-00000000000b/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
        principal = "00000000-0000-0000-0000-0000000000f1"
        type      = "ServicePrincipal"
      }),
      jsonencode({
        scope     = "/subscriptions/00000000-0000-0000-0000-00000000000b/resourceGroups/rg-sample-demo-sea/providers/Microsoft.Insights/components/appi-sample-demo-sea"
        role      = "/subscriptions/00000000-0000-0000-0000-00000000000b/providers/Microsoft.Authorization/roleDefinitions/3913510d-42f4-4e42-8a64-420c390055eb"
        principal = "00000000-0000-0000-0000-0000000000f1"
        type      = "ServicePrincipal"
      }),
    ])
    error_message = "The hosted agent's identity must get exactly Foundry User on the project and Monitoring Metrics Publisher on Application Insights, as a service principal."
  }
}

run "story_4_1_rejects_an_idle_timeout_outside_the_foundry_limits" {
  command = plan

  override_data {
    target = data.terraform_remote_state.foundation
    values = {
      outputs = {}
    }
  }

  variables {
    agent_idle_timeout_seconds = 7200
  }

  expect_failures = [var.agent_idle_timeout_seconds]
}
