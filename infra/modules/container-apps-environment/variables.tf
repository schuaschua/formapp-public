variable "name" {
  description = "Name of the Container Apps environment."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the environment."
  type        = string
}

variable "location" {
  description = "Azure region of the environment."
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the Log Analytics workspace that receives the environment's logs from creation."
  type        = string
}

variable "tags" {
  description = "Tags applied to the environment."
  type        = map(string)
}
