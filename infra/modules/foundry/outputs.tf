output "account_id" {
  description = "Resource ID of the Foundry account."
  value       = azurerm_cognitive_account.this.id
}

output "account_name" {
  description = "Name of the Foundry account."
  value       = azurerm_cognitive_account.this.name
}

output "project_id" {
  description = "Resource ID of the Foundry project."
  value       = azurerm_cognitive_account_project.this.id
}

output "project_name" {
  description = "Name of the Foundry project."
  value       = azurerm_cognitive_account_project.this.name
}

# Built from the names, so it is known at plan time: https://<subdomain>.services.ai.azure.com/api/projects/<project>
# (the format the Foundry SDKs and REST reference document).
output "project_endpoint" {
  description = "Foundry project endpoint (data plane) for agents, Responses calls and model inference."
  value       = "https://${azurerm_cognitive_account.this.custom_subdomain_name}.services.ai.azure.com/api/projects/${azurerm_cognitive_account_project.this.name}"
}

output "project_principal_id" {
  description = "Principal ID of the project's system identity (it pulls hosted-agent images)."
  value       = azurerm_cognitive_account_project.this.identity[0].principal_id
}

output "model_deployment_name" {
  description = "Name of the active model deployment (active_model_deployment, else the first deployment)."
  value = (
    var.active_model_deployment == null || var.active_model_deployment == var.model_deployment_name
    ? azurerm_cognitive_deployment.this.name
    : azurerm_cognitive_deployment.next[0].name
  )
}

output "model_deployment_names" {
  description = "Names of every model deployment on the account."
  value       = concat([azurerm_cognitive_deployment.this.name], azurerm_cognitive_deployment.next[*].name)
}

output "capability_host_id" {
  description = "Resource ID of the account's Agents capability host."
  value       = azapi_resource.capability_host.id
}
