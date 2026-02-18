version: 2
ethernets:
  eth0:
    dhcp4: false
    addresses:
      - ${ip_address}
    routes:
      - to: default
        via: ${gateway}
    nameservers:
      addresses:
%{ for dns in dns_servers ~}
        - ${dns}
%{ endfor ~}
