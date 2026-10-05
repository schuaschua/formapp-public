output "id" {
  description = "Resource ID of the storage account."
  value       = module.storage_account.resource_id
}

output "name" {
  description = "Name of the storage account."
  value       = module.storage_account.name
}

output "container_ids" {
  description = "Resource ID of each blob container, by name (the scope for container-level role assignments)."
  value       = { for key, container in module.storage_account.containers : key => container.id }
}

output "container_urls" {
  description = "Blob endpoint URL of each container, by name (Azure public cloud)."
  value       = { for name in var.container_names : name => "https://${var.name}.blob.core.windows.net/${name}" }
}
