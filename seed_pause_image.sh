#!/bin/bash

# --- Configuration ---
HOSTS_FILE="ips.txt"
USERNAME="kalm"
PAUSE_IMAGE="rancher/mirrored-pause:3.6"
SAVE_FILE="pause_image.tar"

# 1. Download and save the image on your local machine (laptop)
echo "[*] Downloading $PAUSE_IMAGE to your local machine..."
docker pull --platform linux/arm64 $PAUSE_IMAGE
docker save $PAUSE_IMAGE > $SAVE_FILE

if [ ! -f "$HOSTS_FILE" ]; then
    echo "Error: $HOSTS_FILE not found."
    exit 1
fi

# 2. Distribute and load the image on every node
while read -r IP || [ -n "$IP" ]; do
    [[ -z "$IP" || "$IP" == \#* ]] && continue

    echo "[*] Sideloading to $IP..."

    # Copy the tarball to the node
    scp $SAVE_FILE "$USERNAME@$IP:/tmp/$SAVE_FILE"

    # Use nerdctl to load the image into the k8s.io namespace
    ssh "$USERNAME@$IP" << EOF
        sudo nerdctl -n k8s.io load -i /tmp/$SAVE_FILE
        rm /tmp/$SAVE_FILE
        echo "[+] Image loaded successfully on $IP"
EOF

    echo "------------------------------------------"
done < "$HOSTS_FILE"

# Cleanup local file
rm $SAVE_FILE
echo "Done. The cluster now has the pause image cached locally."
