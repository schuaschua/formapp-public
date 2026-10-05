variable "name" {
  description = "Name of the PostgreSQL flexible server."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the server."
  type        = string
}

variable "location" {
  description = "Azure region of the server."
  type        = string
}

variable "postgresql_version" {
  description = "PostgreSQL major version."
  type        = string
}

variable "sku_name" {
  description = "Compute SKU (Burstable tier)."
  type        = string
}

variable "storage_mb" {
  description = "Storage size in MB; storage can't be scaled down later."
  type        = number
}

variable "backup_retention_days" {
  description = "Point-in-time restore window in days."
  type        = number
  default     = 7
}

variable "tenant_id" {
  description = "Entra tenant ID used for PostgreSQL Entra authentication."
  type        = string
}

variable "entra_admin_object_id" {
  description = "Object ID of the Entra security group that is the server's Entra administrator."
  type        = string
}

variable "entra_admin_name" {
  description = "Display name of the Entra administrator group (the PostgreSQL role name its members sign in as)."
  type        = string
}

variable "azure_services_firewall_rule_name" {
  description = "Name of the firewall rule that allows Azure services (0.0.0.0)."
  type        = string
}

variable "tags" {
  description = "Tags applied to the server."
  type        = map(string)
}

variable "allow_public_access" {
  description = "TEMPORARY exception: when true, a firewall rule accepts connections from any IPv4 address (Entra-only auth and verified TLS still apply)."
  type        = bool
  default     = false
}

variable "public_access_firewall_rule_name" {
  description = "Name of the temporary allow-all firewall rule, used only when allow_public_access is true."
  type        = string
}
