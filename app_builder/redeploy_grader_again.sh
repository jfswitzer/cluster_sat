#!/bin/bash

# --- Configuration ---
APP_NAME=$1  # e.g., "matrix", "sort", "primes"
USERNAME="kalm"
HOSTS_FILE="ips.txt"
PLATFORM="linux/arm64"
K3S_IMPORT_DIR="/var/lib/rancher/k3s/agent/images"
# This prefix is vital to match what K3s expects locally
FULL_IMAGE_NAME="docker.io/library/local-grader-$APP_NAME:latest"

if [ -z "$APP_NAME" ]; then
    echo "Usage: ./redeploy_grader.sh <app_name>"
    echo "Example: ./redeploy_grader.sh matrix"
    exit 1
fi

if [ ! -d "apps/$APP_NAME" ]; then
    echo "Error: Directory apps/$APP_NAME/ not found."
    exit 1
fi

echo "--- [1/5] Building $APP_NAME for $PLATFORM (NO CACHE) ---"

# Create a temporary Dockerfile in the app directory
cat <<EOF > "apps/$APP_NAME/Dockerfile"
FROM python:3.11-slim-bullseye
WORKDIR /app
COPY grader.py .
COPY submission.py .
# Ensure we see updates by printing a timestamp
RUN echo "Built at: \$(date)" > /app/build_info.txt
ENTRYPOINT ["python", "grader.py"]
EOF

# FIX: Added --no-cache to ensure Python file changes are picked up
docker buildx build --platform "$PLATFORM" \
    -t "$FULL_IMAGE_NAME" \
    --no-cache \
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
    ssh -n "$USERNAME@$IP" "sudo mv /tmp/$TAR_FILE $K3S_IMPORT_DIR/$TAR_FILE"

done < "$HOSTS_FILE"

echo "--- [4/5] Forcing Re-import & Explicit Tagging ---"
while read -r IP || [ -n "$IP" ]; do
    [[ -z "$IP" || "$IP" == \#* ]] && continue
    echo "[*] Processing image on $IP..."
    
    ssh -n "$USERNAME@$IP" << EOF
        # 1. Kill any existing pods using the old image (to unlock the image)
        # Note: This targets the specific app-type label used in your benchmark
        sudo k3s kubectl delete pods -l app-type=$APP_NAME --force --grace-period=0 > /dev/null 2>&1

        # 2. Clean up ALL existing references for this app
        EXISTING_REFS=\$(sudo k3s ctr -n k8s.io images list -q | grep "$APP_NAME")
        for ref in \$EXISTING_REFS; do
            sudo k3s ctr -n k8s.io images remove "\$ref" > /dev/null 2>&1
        done

        # 3. Manually trigger the import
        sudo k3s ctr -n k8s.io images import "$K3S_IMPORT_DIR/$TAR_FILE" > /dev/null
        
        # 4. Find the RAW SHA256 digest and force-apply tags
        NEW_SHA=\$(sudo k3s ctr -n k8s.io images list | grep "$APP_NAME" | grep -o "sha256:[a-f0-9]\{64\}" | head -n 1)
        
        if [ ! -z "\$NEW_SHA" ]; then
            echo "    Found Digest: \$NEW_SHA"
            sudo k3s ctr -n k8s.io images tag "\$NEW_SHA" "$FULL_IMAGE_NAME" > /dev/null
            sudo k3s ctr -n k8s.io images tag "\$NEW_SHA" "local-grader-$APP_NAME:latest" > /dev/null
        else
            echo "    [!] Error: Could not find digest for $APP_NAME on \$IP"
        fi
EOF
done < "$HOSTS_FILE"

echo "--- [5/5] Verification ---"
SAMPLE_IP=$(grep -v '^#' "$HOSTS_FILE" | head -n 1)
echo "Checking representative node: $SAMPLE_IP"
REMOTE_INFO=$(ssh -n "$USERNAME@$SAMPLE_IP" "sudo k3s ctr -n k8s.io images list | grep $APP_NAME | grep latest")

if [ ! -z "$REMOTE_INFO" ]; then
    echo "SUCCESS: $APP_NAME updated and explicitly tagged as :latest"
    echo "New Image Info: $REMOTE_INFO"
else
    echo "ERROR: Image tag ':latest' still missing on $SAMPLE_IP."
fi

# Cleanup local tar
rm "$TAR_FILE"
echo "Done. Ensure you delete old jobs before starting a new benchmark run!"
