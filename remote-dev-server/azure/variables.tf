variable "resource_group_name" {
  description = "Name of an existing Azure Resource Group"
  type        = string
}

variable "tailscale_auth_key" {
  description = "Tailscale auth key for joining the VM to your tailnet. Create at https://login.tailscale.com/admin/settings/keys (reusable, ephemeral recommended)"
  type        = string
  sensitive   = true
}

variable "vm_name" {
  description = "Name of the VM in Azure and hostname in Tailscale"
  type        = string
  default     = "devbox"
}

variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "westeurope"
}

variable "vm_size" {
  description = "Azure VM size (SKU)"
  type        = string
  default     = "Standard_B4as_v2"
}

variable "os_disk_size_gb" {
  description = "OS disk size in GB"
  type        = number
  default     = 128
}

variable "os_disk_type" {
  description = "OS disk storage account type (StandardSSD_LRS or Premium_LRS)"
  type        = string
  default     = "StandardSSD_LRS"
}

variable "admin_username" {
  description = "Admin username on the VM"
  type        = string
  default     = "devuser"
}

variable "ssh_public_key" {
  description = "Path to SSH public key file (fallback auth if Tailscale SSH is unavailable)"
  type        = string
  default     = "~/.ssh/id_ed25519_devbox.pub"
}

variable "auto_shutdown_time" {
  description = "Daily auto-shutdown time in HHMM format (local time)"
  type        = string
  default     = "2200"
}

variable "auto_shutdown_timezone" {
  description = "Timezone for auto-shutdown schedule"
  type        = string
  default     = "Central Europe Standard Time"
}

variable "portal_domain" {
  description = "Domain for Portal dashboard links (e.g. cc-ts.backovsky.eu). If empty, Tailscale hostname auto-detection is used."
  type        = string
  default     = ""
}
