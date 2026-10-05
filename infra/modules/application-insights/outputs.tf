output "id" {
  description = "Resource ID of the Application Insights resource."
  value       = azurerm_application_insights.this.id
}

output "name" {
  description = "Name of the Application Insights resource."
  value       = azurerm_application_insights.this.name
}

output "connection_string" {
  description = "Connection string for the Azure Monitor distro (instrumentation key and endpoints); ingestion also needs an Entra token, and it is still passed only as a Container Apps secret."
  value       = azurerm_application_insights.this.connection_string
  sensitive   = true
}

output "workspace_id" {
  description = "Resource ID of the Log Analytics workspace the telemetry is stored in."
  value       = azurerm_application_insights.this.workspace_id
}
