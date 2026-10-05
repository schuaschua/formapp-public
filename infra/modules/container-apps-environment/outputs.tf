output "id" {
  description = "Resource ID of the Container Apps environment."
  value       = azurerm_container_app_environment.this.id
}

output "default_domain" {
  description = "Default DNS domain of the environment."
  value       = azurerm_container_app_environment.this.default_domain
}
