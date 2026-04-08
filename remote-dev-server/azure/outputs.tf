output "vm_id" {
  description = "Azure resource ID of the VM"
  value       = azurerm_linux_virtual_machine.main.id
}

output "vm_private_ip" {
  description = "Private IP address in Azure VNet (not the Tailscale IP)"
  value       = azurerm_linux_virtual_machine.main.private_ip_address
}

output "tailscale_note" {
  description = "How to find the Tailscale IP address"
  value       = "Tailscale IP is assigned after VM boot. Find it at https://login.tailscale.com/admin/machines or run: ssh ${var.admin_username}@${var.vm_name} -- tailscale ip -4"
}

output "portainer_url" {
  description = "Portainer web UI URL (replace <TAILSCALE_IP> with actual IP)"
  value       = "https://<TAILSCALE_IP>:9443"
}

output "ssh_command" {
  description = "SSH command using Tailscale hostname"
  value       = "ssh ${var.admin_username}@${var.vm_name}"
}
