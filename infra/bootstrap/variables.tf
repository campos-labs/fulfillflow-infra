variable "subscription_id" {
  type        = string
  description = "Explicit subscription approved for this backend."
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "Use an explicit Azure subscription UUID."
  }
}

variable "tenant_id" {
  type        = string
  description = "Explicit Entra tenant; no credentials belong in Terraform inputs."
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "Use an explicit Entra tenant UUID."
  }
}

variable "location" {
  type        = string
  description = "Azure region selected after availability and cost review."
  validation {
    condition     = length(trimspace(var.location)) > 0
    error_message = "An explicit region is required."
  }
}

variable "resource_group_name" {
  type        = string
  description = "Dedicated persistent backend resource group, separate from runtime."
}

variable "storage_account_name" {
  type        = string
  description = "Globally unique backend account name."
  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "The account name must contain 3–24 lowercase letters or digits."
  }
}

variable "replication_type" {
  type        = string
  description = "Approved Storage replication SKU; no implicit cost selection."
  validation {
    condition     = contains(["LRS", "ZRS", "GRS", "RAGRS", "GZRS", "RAGZRS"], var.replication_type)
    error_message = "Select a supported Standard Storage replication type."
  }
}

variable "retention_days" {
  type        = number
  description = "Approved soft-delete retention for state blobs and containers."
  validation {
    condition     = var.retention_days >= 1 && var.retention_days <= 365 && floor(var.retention_days) == var.retention_days
    error_message = "Retention must be a whole number of days from 1 to 365."
  }
}

variable "allowed_ipv4_addresses" {
  type        = set(string)
  description = "Explicit public egress IPv4 addresses for state operators, without CIDR suffix. Storage rejects /32 notation."
  validation {
    condition = length(var.allowed_ipv4_addresses) > 0 && alltrue([
      for address in var.allowed_ipv4_addresses : can(cidrnetmask("${address}/32")) && can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}$", address))
    ])
    error_message = "Provide one or more valid individual IPv4 addresses, never CIDR ranges or wildcards."
  }
}

variable "cost_approval_confirmed" {
  type        = bool
  default     = false
  description = "Set only after authorization of this concrete target, cost and permissions. Validation does not authorize provisioning."
}

variable "cost_approval_reference" {
  type        = string
  default     = ""
  description = "Reference to the approved environment/cost record; no personal or secret data."
}
