# This root initially uses sensitive local state. See ../README.md before bootstrap.
resource "terraform_data" "approval" {
  lifecycle {
    precondition {
      condition     = var.cost_approval_confirmed && length(trimspace(var.cost_approval_reference)) > 0
      error_message = "Provisioning is blocked until the concrete backend target, cost and permissions are approved and recorded."
    }
  }
}

resource "azurerm_resource_group" "state" {
  name     = var.resource_group_name
  location = var.location
  tags     = { application = "fulfillflow", purpose = "terraform-state" }

  depends_on = [terraform_data.approval]
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_account" "state" {
  name                             = var.storage_account_name
  resource_group_name              = azurerm_resource_group.state.name
  location                         = azurerm_resource_group.state.location
  account_tier                     = "Standard"
  account_kind                     = "StorageV2"
  account_replication_type         = var.replication_type
  min_tls_version                  = "TLS1_2"
  https_traffic_only_enabled       = true
  shared_access_key_enabled        = false
  default_to_oauth_authentication  = true
  allow_nested_items_to_be_public  = false
  public_network_access_enabled    = true
  cross_tenant_replication_enabled = false

  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
    ip_rules       = var.allowed_ipv4_addresses
  }

  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = var.retention_days
    }
    container_delete_retention_policy {
      days = var.retention_days
    }
  }

  tags = azurerm_resource_group.state.tags
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_container" "state" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"

  lifecycle {
    prevent_destroy = true
  }
}
