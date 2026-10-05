output "id" {
  description = "Resource ID of the resource group."
  value       = module.resource_group.resource_id
}

output "name" {
  description = "Name of the resource group."
  value       = module.resource_group.name
}
