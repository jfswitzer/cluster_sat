#!/bin/bash

# --- Configuration ---
HOSTS_FILE="ips.txt"
USERNAME="kalm"
REGISTRY_IP="10.0.0.1"   # CHANGE THIS to your Registry Node's IP
REGISTRY_PORT="30500"

# The content of the registries.yaml file
REGISTRY_CONFIG=$(cat <<EOF
mirrors:
  "$REGISTRY_IP:$REGISTRY_PORT":
    endpoint:
      - "http://$REGISTRY_IP:$REGISTRY_PORT"
EOF
)

if [ ! -f "$HOSTS_FILE" ]; then
    echo "Error: $HOSTS_FILE not found."
    exit 1
fi

echo "--- Distributing K3s Registry Config to Cluster ---"

# Cleaned loop: reads each line, trims whitespace, and skips empty/commented lines
while read -r IP || [ -n "$IP" ]; do
    # Skip empty lines or lines starting with #
    [[ -z "$IP" || "$IP" == \#* ]] && continue

    echo "[*] Configuring node: $IP"

    ssh -o BatchMode=yes -o ConnectTimeout=5 "$USERNAME@$IP" << EOF
        sudo mkdir -p /etc/rancher/k3s
        echo "$REGISTRY_CONFIG" | sudo tee /etc/rancher/k3s/registries.yaml > /dev/null
        echo "[+] Config written. Restarting K3s..."
        if systemctl is-active --quiet k3s; then
            sudo systemctl restart k3s
        else
            sudo systemctl restart k3s-agent
        fi
EOF

    if [ $? -eq 0 ]; then
        echo "[SUCCESS] $IP is ready."
    else
        echo "[FAILED] Could not configure $IP"
    fi
    echo "------------------------------------------"

done < "$HOSTS_FILE"

echo "Done."
