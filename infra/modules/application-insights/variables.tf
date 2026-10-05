variable "name" {
  description = "Name of the Application Insights resource."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the Application Insights resource."
  type        = string
}

variable "location" {
  description = "Azure region of the Application Insights resource (the workspace's region)."
  type        = string
}

variable "workspace_id" {
  description = "Resource ID of the Log Analytics workspace that stores the telemetry."
  type        = string
}

variable "tags" {
  description = "Tags applied to the Application Insights resource."
  type        = map(string)
}
