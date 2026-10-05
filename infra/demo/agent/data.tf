# The only way this stack learns about foundation (terraform.md rules 7-8).
data "terraform_remote_state" "foundation" {
  backend = "azurerm"

  config = {
    storage_account_name = var.state_storage_account_name
    container_name       = var.state_container_name
    key                  = var.foundation_state_key
    use_azuread_auth     = true
  }
}
