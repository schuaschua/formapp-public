# Hand-written azurerm: the latest AVM module, Azure/avm-res-dbforpostgresql-flexibleserver 0.2.3,
# requires azurerm ~> 4.12 and cannot run with the pinned azurerm 5.7.0 (spine Stack).
# Replace with the AVM module once a release supports azurerm 5.x.
resource "azurerm_postgresql_flexible_server" "this" {
  name                          = var.name
  resource_group_name           = var.resource_group_name
  location                      = var.location
  version                       = var.postgresql_version
  sku_name                      = var.sku_name
  storage_mb                    = var.storage_mb
  auto_grow_enabled             = false
  backup_retention_days         = var.backup_retention_days
  geo_redundant_backup_enabled  = false
  public_network_access_enabled = true

  # Entra-only: password authentication is off, so no administrator_login/password exists.
  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
    tenant_id                     = var.tenant_id
  }

  # No high_availability block: the POC runs without HA (azure.md rule 23).

  tags = var.tags

  lifecycle {
    # Azure picks the availability zone at creation; don't fight it on later plans.
    ignore_changes = [zone]
  }
}

# The three child resources below are chained with depends_on (configuration, then firewall rule,
# then Entra admin): Azure serialises changes on one flexible server and rejects parallel ones (ServerBusy).
resource "azurerm_postgresql_flexible_server_configuration" "require_secure_transport" {
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "on"
}

# 0.0.0.0-0.0.0.0 is Azure's special rule for "allow Azure services"; no other rule is managed here
# (temporary operator and runner rules are out-of-band, azure.md rule 13).
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = var.azure_services_firewall_rule_name
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"

  depends_on = [azurerm_postgresql_flexible_server_configuration.require_secure_transport]
}

# Story 1.5: server errors are logged without DETAIL, which can quote row values (answers), before
# they reach the workspace through the PostgreSQLLogs diagnostic setting (security.md rule 2).
# Chained after the other server changes: Azure applies one server operation at a time.
resource "azurerm_postgresql_flexible_server_configuration" "log_error_verbosity" {
  name      = "log_error_verbosity"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "TERSE"

  depends_on = [azurerm_postgresql_flexible_server_active_directory_administrator.this]
}

# TEMPORARY owner-approved exception (owner, 2026-09-26): accept connections from any IPv4 address
# while allow_public_access is true. Sign-in still needs an Entra token and verified TLS; set the
# variable to false to close it (azure.md rule 13 exception).
resource "azurerm_postgresql_flexible_server_firewall_rule" "public" {
  count = var.allow_public_access ? 1 : 0

  name             = var.public_access_firewall_rule_name
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "255.255.255.255"

  depends_on = [azurerm_postgresql_flexible_server_configuration.log_error_verbosity]
}

resource "azurerm_postgresql_flexible_server_active_directory_administrator" "this" {
  server_name         = azurerm_postgresql_flexible_server.this.name
  resource_group_name = var.resource_group_name
  tenant_id           = var.tenant_id
  object_id           = var.entra_admin_object_id
  principal_name      = var.entra_admin_name
  principal_type      = "Group"

  depends_on = [azurerm_postgresql_flexible_server_firewall_rule.azure_services]
}
