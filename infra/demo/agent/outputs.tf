output "api_image" {
  description = "The api image this stack sets on the Container App (null until foundation has been applied)."
  value       = local.api_image
}

output "agent_image" {
  description = "The image of the hosted agent's current version (null until foundation has the Foundry resources)."
  value       = local.agent_image
}

output "hosted_agent_name" {
  description = "Name of the hosted agent (null until foundation has the Foundry resources)."
  value       = one(azapi_data_plane_resource.hosted_agent[*].name)
}
