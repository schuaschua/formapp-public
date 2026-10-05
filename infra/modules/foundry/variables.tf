variable "account_name" {
  description = "Name of the Foundry account (kind AIServices); also its custom subdomain."
  type        = string
}

variable "project_name" {
  description = "Name of the Foundry project in the account."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the Foundry account."
  type        = string
}

variable "location" {
  description = "Azure region of the Foundry account and project."
  type        = string
}

variable "sku_name" {
  description = "SKU of the Foundry account."
  type        = string
}

variable "capability_host_name" {
  description = "Name of the account capability host that enables hosted agents."
  type        = string
}

variable "model_deployment_name" {
  description = "Name of the model deployment; code receives it only as configuration."
  type        = string
}

variable "model_format" {
  description = "Model format (publisher) of the deployment, for example OpenAI."
  type        = string
}

variable "model_name" {
  description = "Model name of the deployment."
  type        = string
}

variable "model_version" {
  description = "Model version of the deployment (pinned; auto-upgrade is off)."
  type        = string
}

variable "model_sku_name" {
  description = "Deployment type of the model, for example GlobalStandard."
  type        = string
}

variable "model_capacity" {
  description = "Deployment capacity in thousands of tokens per minute."
  type        = number

  validation {
    condition     = var.model_capacity >= 1 && floor(var.model_capacity) == var.model_capacity
    error_message = "model_capacity must be a whole number of at least 1 (thousands of tokens per minute)."
  }
}

variable "next_model_deployment" {
  description = "Optional second model deployment on the same account, so the model can be switched without replacing the first deployment. Null for none."
  type = object({
    name     = string
    format   = string
    model    = string
    version  = string
    sku_name = string
    capacity = number
  })
  default = null

  validation {
    condition     = var.next_model_deployment == null ? true : (var.next_model_deployment.capacity >= 1 && floor(var.next_model_deployment.capacity) == var.next_model_deployment.capacity)
    error_message = "next_model_deployment.capacity must be a whole number of at least 1 (thousands of tokens per minute)."
  }
}

variable "active_model_deployment" {
  description = "Name of the deployment callers use (the model_deployment_name output): model_deployment_name or next_model_deployment.name. Null means model_deployment_name."
  type        = string
  default     = null

  validation {
    condition = var.active_model_deployment == null ? true : contains(
      compact([var.model_deployment_name, try(var.next_model_deployment.name, "")]), var.active_model_deployment
    )
    error_message = "active_model_deployment must name model_deployment_name or next_model_deployment.name."
  }
}

variable "tags" {
  description = "Tags applied to the Foundry account and project."
  type        = map(string)
}
