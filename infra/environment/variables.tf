variable "subscription_id" {
  type        = string
  description = "Explicit subscription approved for this environment."
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "Use an explicit Azure subscription UUID."
  }
}

variable "tenant_id" {
  type        = string
  description = "Entra tenant owning the cluster and deployment identity."
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "Use an explicit Entra tenant UUID."
  }
}

variable "location" {
  type        = string
  description = "Explicit Azure region after quota, availability and cost review."
  validation {
    condition     = length(trimspace(var.location)) > 0
    error_message = "An explicit region is required."
  }
}

variable "resource_group_name" {
  type        = string
  description = "Dedicated environment resource group; never the backend group."
}

variable "node_resource_group_name" {
  type        = string
  description = "Explicit new resource group name reserved for AKS-managed node resources."
}

variable "acr_name" {
  type        = string
  description = "Globally unique registry name, with no admin or anonymous access."
  validation {
    condition     = can(regex("^[a-zA-Z0-9]{5,50}$", var.acr_name))
    error_message = "ACR names must have 5–50 alphanumeric characters."
  }
}

variable "acr_sku" {
  type        = string
  description = "Registry SKU selected in the approved cost estimate."
  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.acr_sku)
    error_message = "Select Basic, Standard or Premium."
  }
}

variable "aks_name" {
  type        = string
  description = "Cluster name and DNS prefix."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,38}[a-z0-9]$", var.aks_name))
    error_message = "Use a lowercase DNS-compatible cluster name from 3 to 40 characters."
  }
}

variable "aks_sku_tier" {
  type        = string
  description = "Control-plane SKU selected in the approved cost estimate."
  validation {
    condition     = contains(["Free", "Standard"], var.aks_sku_tier)
    error_message = "Choose Free or Standard for this functional environment."
  }
}

variable "kubernetes_version" {
  type        = string
  description = "Exact GA patch version verified as available in the chosen region before provisioning."
  validation {
    condition     = can(regex("^1\\.[0-9]+\\.[0-9]+$", var.kubernetes_version))
    error_message = "Pin a full Kubernetes patch version, for example 1.34.7; no minor aliases."
  }
}

variable "node_vm_size" {
  type        = string
  description = "Approved Linux amd64 VM SKU with capacity for requests, system, rollout and Jobs."
  validation {
    condition     = can(regex("^Standard_[A-Za-z0-9_]+$", var.node_vm_size))
    error_message = "Provide an explicit Standard Azure VM SKU."
  }
}

variable "node_count" {
  type        = number
  description = "Approved fixed system node count; cluster autoscaler is disabled."
  validation {
    condition     = var.node_count >= 1 && var.node_count <= 100 && floor(var.node_count) == var.node_count
    error_message = "Specify a whole node count from 1 to 100."
  }
}

variable "node_os_disk_size_gb" {
  type        = number
  description = "Approved managed OS disk capacity per node, distinct from workload PVCs."
  validation {
    condition     = var.node_os_disk_size_gb >= 30 && var.node_os_disk_size_gb <= 2048 && floor(var.node_os_disk_size_gb) == var.node_os_disk_size_gb
    error_message = "Specify a whole disk size from 30 to 2048 GiB."
  }
}

variable "api_allowed_ipv4_cidrs" {
  type        = set(string)
  description = "Nonempty, approved public IPv4 egress addresses of operators/executor, each as /32. No hosted-runner wildcard."
  validation {
    condition = length(var.api_allowed_ipv4_cidrs) > 0 && alltrue([
      for cidr in var.api_allowed_ipv4_cidrs : can(cidrnetmask(cidr)) && can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}/32$", cidr)) && cidr != "0.0.0.0/32"
    ])
    error_message = "Supply at least one valid, explicit IPv4 /32 CIDR. Empty, IPv6, invalid addresses and broad ranges are forbidden."
  }
}

variable "pod_cidr" {
  type        = string
  description = "Approved overlay pod IPv4 range; verify no overlap with service, node or connected networks."
  validation {
    condition     = can(cidrnetmask(var.pod_cidr))
    error_message = "An IPv4 CIDR is required."
  }
}

variable "service_cidr" {
  type        = string
  description = "Approved service IPv4 range; verify no overlap with pod, node or connected networks."
  validation {
    condition     = can(cidrnetmask(var.service_cidr))
    error_message = "An IPv4 CIDR is required."
  }
}

variable "cost_approval_confirmed" {
  type        = bool
  default     = false
  description = "Set only after approval of the concrete target, cost, endpoint and privileges. Tests do not authorize provisioning."
}

variable "cost_approval_reference" {
  type        = string
  default     = ""
  description = "Reference to the approved environment/cost record; no personal or secret data."
}
