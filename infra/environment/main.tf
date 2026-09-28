resource "terraform_data" "approval" {
  lifecycle {
    precondition {
      condition     = var.cost_approval_confirmed && length(trimspace(var.cost_approval_reference)) > 0
      error_message = "Provisioning is blocked until the concrete environment, cost, endpoint and privileges are approved and recorded."
    }
  }
}

resource "azurerm_resource_group" "environment" {
  name     = var.resource_group_name
  location = var.location
  tags     = { application = "fulfillflow", purpose = "functional-environment" }

  depends_on = [terraform_data.approval]
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_container_registry" "runtime" {
  name                   = var.acr_name
  resource_group_name    = azurerm_resource_group.environment.name
  location               = azurerm_resource_group.environment.location
  sku                    = var.acr_sku
  admin_enabled          = false
  anonymous_pull_enabled = false

  # Authenticated public endpoint; this is not Azure Private Link.
  # v4.55.0 does not expose role_assignment_mode. Verify effective RBAC before use.
  public_network_access_enabled = true
  network_rule_bypass_option    = "None"
  tags                          = azurerm_resource_group.environment.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_kubernetes_cluster" "runtime" {
  name                = var.aks_name
  location            = azurerm_resource_group.environment.location
  resource_group_name = azurerm_resource_group.environment.name
  node_resource_group = var.node_resource_group_name
  dns_prefix          = var.aks_name
  kubernetes_version  = var.kubernetes_version
  sku_tier            = var.aks_sku_tier

  role_based_access_control_enabled = true
  # AKS 1.34+ enables this at creation; make the service default explicit.
  oidc_issuer_enabled     = true
  local_account_disabled  = true
  private_cluster_enabled = false
  run_command_enabled     = false
  node_os_upgrade_channel = "None"

  azure_active_directory_role_based_access_control {
    tenant_id          = var.tenant_id
    azure_rbac_enabled = true
  }

  api_server_access_profile {
    authorized_ip_ranges = var.api_allowed_ipv4_cidrs
  }

  default_node_pool {
    name                        = "system"
    temporary_name_for_rotation = "systemtemp"
    vm_size                     = var.node_vm_size
    node_count                  = var.node_count
    auto_scaling_enabled        = false
    orchestrator_version        = var.kubernetes_version
    os_sku                      = "Ubuntu"
    os_disk_type                = "Managed"
    os_disk_size_gb             = var.node_os_disk_size_gb
    node_public_ip_enabled      = false

    upgrade_settings {
      max_surge = "1"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    pod_cidr            = var.pod_cidr
    service_cidr        = var.service_cidr
    dns_service_ip      = cidrhost(var.service_cidr, 10)
    load_balancer_sku   = "standard"
    outbound_type       = "loadBalancer"
    load_balancer_profile {
      managed_outbound_ip_count = 1
    }
  }

  tags = azurerm_resource_group.environment.tags
}

resource "azurerm_role_assignment" "kubelet_pull" {
  scope                            = azurerm_container_registry.runtime.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.runtime.kubelet_identity[0].object_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_user_assigned_identity" "deployment" {
  name                = "${var.aks_name}-deploy"
  resource_group_name = azurerm_resource_group.environment.name
  location            = azurerm_resource_group.environment.location
  tags                = azurerm_resource_group.environment.tags
}

resource "azurerm_federated_identity_credential" "github_main" {
  name                = "github-main"
  resource_group_name = azurerm_resource_group.environment.name
  parent_id           = azurerm_user_assigned_identity.deployment.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:campos-labs/fulfillflow-infra:ref:refs/heads/main"
}

resource "azurerm_role_assignment" "deployment_cluster_user" {
  scope                            = azurerm_kubernetes_cluster.runtime.id
  role_definition_name             = "Azure Kubernetes Service Cluster User Role"
  principal_id                     = azurerm_user_assigned_identity.deployment.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "deployment_namespace_writer" {
  scope                            = "${azurerm_kubernetes_cluster.runtime.id}/namespaces/fulfillflow"
  role_definition_name             = "Azure Kubernetes Service RBAC Writer"
  principal_id                     = azurerm_user_assigned_identity.deployment.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "operator_push" {
  count                = var.grant_operator_access ? 1 : 0
  scope                = azurerm_container_registry.runtime.id
  role_definition_name = "AcrPush"
  principal_id         = var.operator_object_id
  principal_type       = "User"
}

resource "azurerm_role_assignment" "operator_cluster_user" {
  count                = var.grant_operator_access ? 1 : 0
  scope                = azurerm_kubernetes_cluster.runtime.id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = var.operator_object_id
  principal_type       = "User"
}

resource "azurerm_role_assignment" "operator_cluster_admin" {
  count                = var.grant_operator_access ? 1 : 0
  scope                = azurerm_kubernetes_cluster.runtime.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = var.operator_object_id
  principal_type       = "User"
}
