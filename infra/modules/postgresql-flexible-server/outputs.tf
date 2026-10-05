output "id" {
  description = "Resource ID of the server."
  value       = azurerm_postgresql_flexible_server.this.id
}

output "name" {
  description = "Name of the server."
  value       = azurerm_postgresql_flexible_server.this.name
}

output "fqdn" {
  description = "Fully qualified domain name of the server."
  value       = azurerm_postgresql_flexible_server.this.fqdn
}

output "public_access_ip_range" {
  description = "The temporary allow-all firewall rule's IP range, or null when allow_public_access is false."
  value       = var.allow_public_access ? "${azurerm_postgresql_flexible_server_firewall_rule.public[0].start_ip_address}-${azurerm_postgresql_flexible_server_firewall_rule.public[0].end_ip_address}" : null
}
