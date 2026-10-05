variable "name" {
  description = "Name of the Log Analytics workspace."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the workspace."
  type        = string
}

variable "location" {
  description = "Azure region of the workspace."
  type        = string
}

variable "retention_in_days" {
  description = "Data retention in days (30 is the minimum)."
  type        = number
  default     = 30
}

variable "daily_quota_gb" {
  description = "Daily ingestion cap in GB."
  type        = number
  default     = 0.5
}

variable "tags" {
  description = "Tags applied to the workspace."
  type        = map(string)
}
