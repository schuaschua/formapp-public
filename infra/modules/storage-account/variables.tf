variable "name" {
  description = "Name of the storage account (lower case letters and digits only)."
  type        = string
}

variable "location" {
  description = "Azure region of the storage account."
  type        = string
}

variable "resource_group_id" {
  description = "Resource ID of the resource group that holds the storage account."
  type        = string
}

variable "container_names" {
  description = "Names of the private blob containers to create."
  type        = list(string)
}

variable "tags" {
  description = "Tags applied to the storage account."
  type        = map(string)
}
