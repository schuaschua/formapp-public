variable "state_storage_account_name" {
  description = "Storage account that holds the Terraform state (created by infra/bootstrap/state-backend.sh)."
  type        = string
}

variable "state_container_name" {
  description = "Blob container that holds this app's Terraform state."
  type        = string
}

variable "foundation_state_key" {
  description = "State key of the foundation stack, read through terraform_remote_state."
  type        = string
}

variable "image_repository" {
  description = "Repository of the api image in the registry (az acr build pushes <repository>:<commit SHA>)."
  type        = string
}

variable "image_tag" {
  description = "Tag of the api image to deploy: the commit SHA the deploy workflow built (passed with -var)."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$", var.image_tag))
    error_message = "image_tag must be a valid image tag (the commit SHA), for example -var image_tag=$GITHUB_SHA."
  }
}

variable "agent_image_repository" {
  description = "Repository of the agent image in the registry (az acr build pushes <repository>:<commit SHA>; same tag as api)."
  type        = string
}

variable "agent_cpu" {
  description = "vCPU of the hosted agent container, as the Foundry API expects it (a string)."
  type        = string
}

variable "agent_memory" {
  description = "Memory of the hosted agent container (for example 1Gi)."
  type        = string
}

variable "agent_idle_timeout_seconds" {
  description = "Seconds without a request before the hosted agent's compute is released (120-3600)."
  type        = number

  validation {
    condition     = var.agent_idle_timeout_seconds >= 120 && var.agent_idle_timeout_seconds <= 3600
    error_message = "agent_idle_timeout_seconds must be between 120 and 3600 (the Foundry limits)."
  }
}

variable "telemetry_sampling_ratio" {
  description = "Share of agent traces kept, from 0 (none) to 1 (all), passed to the agent as TELEMETRY_SAMPLING_RATIO (azure.md rule 16)."
  type        = number

  validation {
    condition     = var.telemetry_sampling_ratio >= 0 && var.telemetry_sampling_ratio <= 1
    error_message = "telemetry_sampling_ratio must be between 0 and 1."
  }
}
