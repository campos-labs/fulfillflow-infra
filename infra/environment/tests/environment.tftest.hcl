# Only input validation and proposed plan structure. No Azure API or authorization proof.
mock_provider "azurerm" {
  override_during = plan
  mock_resource "azurerm_kubernetes_cluster" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-runtime-test/providers/Microsoft.ContainerService/managedClusters/aks-test"
    }
  }
  mock_resource "azurerm_container_registry" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-runtime-test/providers/Microsoft.ContainerRegistry/registries/ffregistrytest0001"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-runtime-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/deploy-test"
      principal_id = "44444444-4444-4444-4444-444444444444"
      client_id    = "55555555-5555-5555-5555-555555555555"
    }
  }
}

variables {
  subscription_id          = "00000000-0000-0000-0000-000000000000"
  tenant_id                = "11111111-1111-1111-1111-111111111111"
  location                 = "brazilsouth"
  resource_group_name      = "rg-runtime-test"
  node_resource_group_name = "rg-node-test"
  acr_name                 = "ffregistrytest0001"
  acr_sku                  = "Basic"
  aks_name                 = "aks-test"
  aks_sku_tier             = "Free"
  kubernetes_version       = "1.34.7"
  node_vm_size             = "Standard_D4s_v5"
  node_count               = 2
  node_os_disk_size_gb     = 64
  api_allowed_ipv4_cidrs   = ["203.0.113.10/32"]
  pod_cidr                 = "10.244.0.0/16"
  service_cidr             = "10.0.0.0/16"
  cost_approval_confirmed  = true
  cost_approval_reference  = "synthetic-test-only"
}

run "restricted_runtime_structure" {
  command = plan
  # The legacy provider's computed kubelet_identity block cannot be synthesized
  # by mocks. Target only configuration whose computed outputs are mockable.
  plan_options {
    target = [
      azurerm_container_registry.runtime,
      azurerm_kubernetes_cluster.runtime,
      azurerm_federated_identity_credential.github_main,
      azurerm_role_assignment.deployment_cluster_user,
      azurerm_role_assignment.deployment_namespace_writer,
    ]
  }
  assert {
    condition     = azurerm_kubernetes_cluster.runtime.default_node_pool[0].node_count == 2 && !azurerm_kubernetes_cluster.runtime.default_node_pool[0].auto_scaling_enabled && azurerm_kubernetes_cluster.runtime.kubernetes_version == "1.34.7"
    error_message = "The selected fixed capacity and exact version must be preserved."
  }
  assert {
    condition     = azurerm_kubernetes_cluster.runtime.api_server_access_profile[0].authorized_ip_ranges == toset(["203.0.113.10/32"]) && !azurerm_kubernetes_cluster.runtime.private_cluster_enabled
    error_message = "The proposed public API must use the explicit source allowlist."
  }
  assert {
    condition     = azurerm_kubernetes_cluster.runtime.local_account_disabled && azurerm_kubernetes_cluster.runtime.azure_active_directory_role_based_access_control[0].azure_rbac_enabled && !azurerm_kubernetes_cluster.runtime.run_command_enabled
    error_message = "Use Entra RBAC without local admin or the Azure run-command bypass."
  }
  assert {
    condition     = azurerm_kubernetes_cluster.runtime.network_profile[0].network_plugin_mode == "overlay" && azurerm_kubernetes_cluster.runtime.network_profile[0].network_policy == "cilium" && azurerm_kubernetes_cluster.runtime.network_profile[0].network_data_plane == "cilium"
    error_message = "The proposed cluster must provide the policy engine used by manifests."
  }
  assert {
    condition     = !azurerm_container_registry.runtime.admin_enabled && !azurerm_container_registry.runtime.anonymous_pull_enabled
    error_message = "Registry access must not allow admin credentials or anonymous pull."
  }
  assert {
    condition     = azurerm_federated_identity_credential.github_main.subject == "repo:campos-labs/fulfillflow-infra:ref:refs/heads/main" && azurerm_federated_identity_credential.github_main.issuer == "https://token.actions.githubusercontent.com"
    error_message = "OIDC trust must be restricted to this repository's main branch."
  }
  assert {
    condition     = azurerm_role_assignment.deployment_cluster_user.role_definition_name == "Azure Kubernetes Service Cluster User Role" && azurerm_role_assignment.deployment_cluster_user.scope == azurerm_kubernetes_cluster.runtime.id && azurerm_role_assignment.deployment_namespace_writer.role_definition_name == "Azure Kubernetes Service RBAC Writer" && azurerm_role_assignment.deployment_namespace_writer.scope == "${azurerm_kubernetes_cluster.runtime.id}/namespaces/fulfillflow"
    error_message = "Deployment privileges must be cluster-user and namespace-scoped runtime writer."
  }
}

run "blocks_unapproved_cost" {
  command = plan
  plan_options {
    target = [azurerm_kubernetes_cluster.runtime]
  }
  variables {
    cost_approval_confirmed = false
  }
  expect_failures = [terraform_data.approval]
}

run "requires_approval_record" {
  command = plan
  plan_options {
    target = [azurerm_kubernetes_cluster.runtime]
  }
  variables {
    cost_approval_reference = ""
  }
  expect_failures = [terraform_data.approval]
}

run "rejects_empty_api_allowlist" {
  command = plan
  plan_options {
    target = [azurerm_kubernetes_cluster.runtime]
  }
  variables {
    api_allowed_ipv4_cidrs = []
  }
  expect_failures = [var.api_allowed_ipv4_cidrs]
}

run "rejects_open_api" {
  command = plan
  plan_options {
    target = [azurerm_kubernetes_cluster.runtime]
  }
  variables {
    api_allowed_ipv4_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.api_allowed_ipv4_cidrs]
}

run "rejects_invalid_api_ipv4" {
  command = plan
  plan_options {
    target = [azurerm_kubernetes_cluster.runtime]
  }
  variables {
    api_allowed_ipv4_cidrs = ["999.1.1.1/32"]
  }
  expect_failures = [var.api_allowed_ipv4_cidrs]
}

run "rejects_api_ipv6" {
  command = plan
  plan_options {
    target = [azurerm_kubernetes_cluster.runtime]
  }
  variables {
    api_allowed_ipv4_cidrs = ["2001:db8::1/32"]
  }
  expect_failures = [var.api_allowed_ipv4_cidrs]
}

run "rejects_network_range" {
  command = plan
  plan_options {
    target = [azurerm_kubernetes_cluster.runtime]
  }
  variables {
    api_allowed_ipv4_cidrs = ["203.0.113.0/24"]
  }
  expect_failures = [var.api_allowed_ipv4_cidrs]
}

run "requires_patch_version" {
  command = plan
  plan_options {
    target = [azurerm_kubernetes_cluster.runtime]
  }
  variables {
    kubernetes_version = "1.34"
  }
  expect_failures = [var.kubernetes_version]
}

run "rejects_fractional_capacity" {
  command = plan
  plan_options {
    target = [azurerm_kubernetes_cluster.runtime]
  }
  variables {
    node_count = 1.5
  }
  expect_failures = [var.node_count]
}
