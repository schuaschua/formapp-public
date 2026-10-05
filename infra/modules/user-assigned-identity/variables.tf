variable "name" {
  description = "Name of the user-assigned managed identity."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the identity."
  type        = string
}

variable "location" {
  description = "Azure region of the identity."
  type        = string
}

variable "tags" {
  description = "Tags applied to the identity."
  type        = map(string)
}
