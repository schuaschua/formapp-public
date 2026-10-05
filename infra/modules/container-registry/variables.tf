variable "name" {
  description = "Name of the container registry (alphanumeric only)."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the registry."
  type        = string
}

variable "location" {
  description = "Azure region of the registry."
  type        = string
}

variable "sku" {
  description = "Registry SKU."
  type        = string
  default     = "Basic"
}

variable "tags" {
  description = "Tags applied to the registry."
  type        = map(string)
}
