# Input and plan-structure tests only. Mocks do not verify Azure permissions or Storage.
mock_provider "azurerm" {
  override_during = plan
  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-state-test/providers/Microsoft.Storage/storageAccounts/ffstatetest0001"
    }
  }
}

variables {
  subscription_id         = "00000000-0000-0000-0000-000000000000"
  tenant_id               = "11111111-1111-1111-1111-111111111111"
  location                = "brazilsouth"
  resource_group_name     = "rg-state-test"
  storage_account_name    = "ffstatetest0001"
  replication_type        = "LRS"
  retention_days          = 30
  allowed_ipv4_addresses  = ["203.0.113.10"]
  cost_approval_confirmed = true
  cost_approval_reference = "synthetic-test-only"
}

run "private_entra_backend" {
  command = plan
  assert {
    condition     = !azurerm_storage_account.state.shared_access_key_enabled && azurerm_storage_account.state.default_to_oauth_authentication
    error_message = "State must require Entra authentication instead of shared account keys."
  }
  assert {
    condition     = !azurerm_storage_account.state.allow_nested_items_to_be_public && azurerm_storage_container.state.container_access_type == "private"
    error_message = "State blobs and containers must not permit anonymous access."
  }
  assert {
    condition     = azurerm_storage_account.state.network_rules[0].default_action == "Deny" && azurerm_storage_account.state.network_rules[0].ip_rules == toset(["203.0.113.10"]) && azurerm_storage_account.state.network_rules[0].bypass == toset(["None"])
    error_message = "Storage must allow only the selected operator egress addresses."
  }
  assert {
    condition     = azurerm_storage_account.state.blob_properties[0].versioning_enabled && azurerm_storage_account.state.blob_properties[0].delete_retention_policy[0].days == 30 && azurerm_storage_account.state.blob_properties[0].container_delete_retention_policy[0].days == 30
    error_message = "State needs versioning and the explicitly selected deletion retention."
  }
}

run "blocks_unapproved_cost" {
  command = plan
  variables {
    cost_approval_confirmed = false
  }
  expect_failures = [terraform_data.approval]
}

run "requires_approval_record" {
  command = plan
  variables {
    cost_approval_reference = ""
  }
  expect_failures = [terraform_data.approval]
}

run "rejects_empty_allowlist" {
  command = plan
  variables {
    allowed_ipv4_addresses = []
  }
  expect_failures = [var.allowed_ipv4_addresses]
}

run "rejects_invalid_ipv4" {
  command = plan
  variables {
    allowed_ipv4_addresses = ["999.1.1.1"]
  }
  expect_failures = [var.allowed_ipv4_addresses]
}

run "rejects_broad_allowlist" {
  command = plan
  variables {
    allowed_ipv4_addresses = ["0.0.0.0/0"]
  }
  expect_failures = [var.allowed_ipv4_addresses]
}
