#!/bin/bash

# --- Configuration ---
APP_NAME=$1  # e.g., "matrix", "sort", "primes"
USERNAME="kalm"
HOSTS_FILE="ips.txt"
PLATFORM="linux/arm64"
K3S_IMPORT_DIR="/var/lib/rancher/k3s/agent/images"
# This prefix is vital to match what K3s expects locally
FULL_IMAGE_NAME="docker.io/nathanrliu/local-grader-$APP_NAME:latest"

if [ -z "$APP_NAME" ]; then
    echo "Usage: ./redeploy_grader.sh <app_name>"
    echo "Example: ./redeploy_grader.sh matrix"
    exit 1
fi

if [ ! -d "apps/$APP_NAME" ]; then
    echo "Error: Directory apps/$APP_NAME/ not found."
    exit 1
fi

echo "--- [1/5] Building $APP_NAME for $PLATFORM ---"

# Create a temporary Dockerfile in the app directory
cat <<EOF > "apps/$APP_NAME/Dockerfile"
FROM python:3.11-slim-bullseye
WORKDIR /app
COPY grader.py .
COPY submission.py .
ENTRYPOINT ["python", "grader.py"]
EOF

# Build the image
docker buildx build --platform "$PLATFORM" \
    -t "$FULL_IMAGE_NAME" \
    "apps/$APP_NAME" --load

if [ $? -ne 0 ]; then echo "Build failed!"; exit 1; fi

echo "--- [2/5] Exporting to Tarball ---"
TAR_FILE="local-grader-$APP_NAME.tar"
docker save "$FULL_IMAGE_NAME" > "$TAR_FILE"

# Get the Image ID to verify later
LOCAL_IMAGE_ID=$(docker images --format "{{.ID}}" "$FULL_IMAGE_NAME")
echo "Local Image ID: $LOCAL_IMAGE_ID"

echo "--- [3/5] Distributing to 20 Nodes ---"
while read -r IP || [ -n "$IP" ]; do
    [[ -z "$IP" || "$IP" == \#* ]] && continue
    echo "[*] Sending to $IP..."
    
    # Upload to a temp location first
    scp "$TAR_FILE" "$USERNAME@$IP:/tmp/$TAR_FILE"
    
    # Move to the K3s magic directory
    # We move it to a staging name first then rename it to trigger the 'create' event correctly
    ssh -n "$USERNAME@$IP" "sudo mv /tmp/$TAR_FILE $K3S_IMPORT_DIR/$TAR_FILE.tmp && sudo mv $K3S_IMPORT_DIR/$TAR_FILE.tmp $K3S_IMPORT_DIR/$TAR_FILE"

done < "$HOSTS_FILE"

echo "--- [4/5] Forcing Re-import (Purging Cache) ---"
while read -r IP || [ -n "$IP" ]; do
    [[ -z "$IP" || "$IP" == \#* ]] && continue
    echo "[*] Purging old image on $IP..."
    
    # Removing the image from containerd forces the auto-importer to reload the .tar file
    ssh -n "$USERNAME@$IP" "sudo k3s ctr -n k8s.io images remove $FULL_IMAGE_NAME || true"
done < "$HOSTS_FILE"

echo "--- [5/5] Verification ---"
# Wait a moment for K3s auto-importer to wake up
echo "Waiting 5 seconds for auto-import..."
sleep 5

# Check the first node in the list as a representative sample
SAMPLE_IP=$(grep -v '^#' "$HOSTS_FILE" | head -n 1)
echo "Checking representative node: $SAMPLE_IP"
REMOTE_INFO=$(ssh -n "$USERNAME@$SAMPLE_IP" "sudo k3s ctr -n k8s.io images list | grep $APP_NAME")

if [[ $REMOTE_INFO == *"latest"* ]]; then
    echo "SUCCESS: $APP_NAME updated and re-imported as :latest"
    echo "$REMOTE_INFO"
else
    echo "WARNING: Image not found in :latest format yet. It may still be importing."
fi

# Cleanup local tar
rm "$TAR_FILE"
echo "Done."
