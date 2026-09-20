output "resource_group_name" {
  value = azurerm_resource_group.environment.name
}

output "aks_name" {
  value = azurerm_kubernetes_cluster.runtime.name
}

output "aks_id" {
  value = azurerm_kubernetes_cluster.runtime.id
}

output "acr_login_server" {
  value = azurerm_container_registry.runtime.login_server
}

output "deployment_client_id" {
  description = "Non-secret OIDC client identifier; this identity has no Terraform/backend/registry-push privileges."
  value       = azurerm_user_assigned_identity.deployment.client_id
}

output "deployment_subject" {
  value = azurerm_federated_identity_credential.github_main.subject
}
