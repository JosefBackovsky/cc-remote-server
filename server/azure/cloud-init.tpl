#cloud-config

package_update: true
package_upgrade: true

packages:
  - apt-transport-https
  - ca-certificates
  - curl
  - gnupg
  - git

write_files:
  - path: /opt/setup/docker.sh
    permissions: '0755'
    content: |
      ${indent(6, docker_sh)}
  - path: /opt/setup/tailscale.sh
    permissions: '0755'
    content: |
      ${indent(6, tailscale_sh)}
  - path: /opt/setup/portainer.sh
    permissions: '0755'
    content: |
      ${indent(6, portainer_sh)}
  - path: /opt/setup/shared-volumes.sh
    permissions: '0755'
    content: |
      ${indent(6, shared_volumes_sh)}
  - path: /opt/setup/portal.sh
    permissions: '0755'
    content: |
      ${indent(6, portal_sh)}

runcmd:
  - /opt/setup/docker.sh ${admin_username}
  - /opt/setup/tailscale.sh ${tailscale_auth_key} ${vm_name}
  - /opt/setup/portainer.sh
  - /opt/setup/shared-volumes.sh ${admin_username}
%{ if portal_domain != "" ~}
  - /opt/setup/portal.sh --domain ${portal_domain}
%{ else ~}
  - /opt/setup/portal.sh
%{ endif ~}
