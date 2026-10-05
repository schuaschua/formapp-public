output "id" {
  description = "Resource ID of the registry."
  value       = azurerm_container_registry.this.id
}

output "login_server" {
  description = "Login server host name of the registry."
  value       = azurerm_container_registry.this.login_server
}

output "name" {
  description = "Name of the registry."
  value       = azurerm_container_registry.this.name
}
