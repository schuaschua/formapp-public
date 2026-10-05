# tflint configuration for every Terraform root and module under infra/.
config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "azurerm" {
  enabled = true
  version = "0.32.0"
  source  = "github.com/terraform-linters/tflint-ruleset-azurerm"
}

# The owner destroys and recreates the demo environment with terraform destroy (azure.md rule 21);
# the data is synthetic, so prevent_destroy would only block that.
rule "azurerm_resources_missing_prevent_destroy" {
  enabled = false
}
