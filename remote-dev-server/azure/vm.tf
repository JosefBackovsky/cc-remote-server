# -----------------------------------------------------------------------------
# Virtual Network
# -----------------------------------------------------------------------------

resource "azurerm_virtual_network" "main" {
  name                = "${var.vm_name}-vnet"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.main.name
  address_space       = ["10.0.0.0/16"]
}

resource "azurerm_subnet" "main" {
  name                 = "${var.vm_name}-subnet"
  resource_group_name  = data.azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.1.0/24"]
}

# -----------------------------------------------------------------------------
# Network Security Group
# -----------------------------------------------------------------------------

resource "azurerm_network_security_group" "main" {
  name                = "${var.vm_name}-nsg"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.main.name

  security_rule {
    name                       = "AllowTailscaleUDP"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Udp"
    source_port_range          = "*"
    destination_port_range     = "41641"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

# -----------------------------------------------------------------------------
# Network Interface
# -----------------------------------------------------------------------------

resource "azurerm_network_interface" "main" {
  name                = "${var.vm_name}-nic"
  location            = var.location
  resource_group_name = data.azurerm_resource_group.main.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.main.id
    private_ip_address_allocation = "Dynamic"
  }
}

resource "azurerm_network_interface_security_group_association" "main" {
  network_interface_id      = azurerm_network_interface.main.id
  network_security_group_id = azurerm_network_security_group.main.id
}

# -----------------------------------------------------------------------------
# Linux Virtual Machine
# -----------------------------------------------------------------------------

resource "azurerm_linux_virtual_machine" "main" {
  name                = var.vm_name
  location            = var.location
  resource_group_name = data.azurerm_resource_group.main.name
  size                = var.vm_size
  admin_username      = var.admin_username

  network_interface_ids = [
    azurerm_network_interface.main.id,
  ]

  admin_ssh_key {
    username   = var.admin_username
    public_key = file(pathexpand(var.ssh_public_key))
  }

  os_disk {
    name                 = "${var.vm_name}-osdisk"
    caching              = "ReadWrite"
    storage_account_type = var.os_disk_type
    disk_size_gb         = var.os_disk_size_gb
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64encode(templatefile("${path.module}/cloud-init.tpl", {
    tailscale_auth_key = var.tailscale_auth_key
    admin_username     = var.admin_username
    vm_name            = var.vm_name
    portal_domain      = var.portal_domain
    docker_sh          = file("${path.module}/../scripts/docker.sh")
    tailscale_sh       = file("${path.module}/../scripts/tailscale.sh")
    portainer_sh       = file("${path.module}/../scripts/portainer.sh")
    shared_volumes_sh  = file("${path.module}/../scripts/shared-volumes.sh")
    portal_sh          = file("${path.module}/../scripts/portal.sh")
  }))

  lifecycle {
    ignore_changes = [custom_data, os_disk[0].disk_size_gb, os_disk[0].storage_account_type]
  }
}

# -----------------------------------------------------------------------------
# OS Disk update (deallocate → change → start, same as Azure Portal)
# -----------------------------------------------------------------------------

resource "terraform_data" "os_disk_update" {
  triggers_replace = {
    disk_size_gb = var.os_disk_size_gb
    disk_type    = var.os_disk_type
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      DISK_NAME="${var.vm_name}-osdisk"
      RG="${data.azurerm_resource_group.main.name}"
      VM_NAME="${var.vm_name}"
      DESIRED_SIZE="${var.os_disk_size_gb}"
      DESIRED_TYPE="${var.os_disk_type}"

      CURRENT_SIZE=$(az disk show -g "$RG" -n "$DISK_NAME" --query "diskSizeGb" -o tsv 2>/dev/null || echo "")
      CURRENT_TYPE=$(az disk show -g "$RG" -n "$DISK_NAME" --query "sku.name" -o tsv 2>/dev/null || echo "")

      if [ "$CURRENT_SIZE" = "$DESIRED_SIZE" ] && [ "$CURRENT_TYPE" = "$DESIRED_TYPE" ]; then
        echo "OS disk already has desired configuration. Skipping."
        exit 0
      fi

      echo "Updating OS disk: size $${CURRENT_SIZE:-?}→$${DESIRED_SIZE}GB, type $${CURRENT_TYPE:-?}→$${DESIRED_TYPE}"
      az vm deallocate -g "$RG" -n "$VM_NAME"
      az disk update -g "$RG" -n "$DISK_NAME" --size-gb "$DESIRED_SIZE" --sku "$DESIRED_TYPE"
      az vm start -g "$RG" -n "$VM_NAME"
      echo "Done."
    EOT
  }

  depends_on = [azurerm_linux_virtual_machine.main]
}

# -----------------------------------------------------------------------------
# Auto-shutdown schedule
# -----------------------------------------------------------------------------

resource "azurerm_dev_test_global_vm_shutdown_schedule" "main" {
  virtual_machine_id = azurerm_linux_virtual_machine.main.id
  location           = var.location
  enabled            = true

  daily_recurrence_time = var.auto_shutdown_time
  timezone              = var.auto_shutdown_timezone

  notification_settings {
    enabled = false
  }
}
