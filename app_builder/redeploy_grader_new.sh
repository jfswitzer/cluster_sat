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
    ssh -n "$USERNAME@$IP" "sudo mv /tmp/$TAR_FILE $K3S_IMPORT_DIR/$TAR_FILE"

done < "$HOSTS_FILE"

echo "--- [4/5] Forcing Re-import & Explicit Tagging ---"
while read -r IP || [ -n "$IP" ]; do
    [[ -z "$IP" || "$IP" == \#* ]] && continue
    echo "[*] Processing image on $IP..."
    
    # We use a multi-stage approach inside the remote shell to ensure a clean state
    ssh -n "$USERNAME@$IP" << EOF
        # 1. Clean up ALL existing references for this app (tags and digests)
        echo "    Cleaning up old references..."
        EXISTING_REFS=\$(sudo k3s ctr -n k8s.io images list -q | grep "$APP_NAME")
        for ref in \$EXISTING_REFS; do
            sudo k3s ctr -n k8s.io images remove "\$ref" > /dev/null 2>&1
        done

        # 2. Manually trigger the import
        echo "    Importing $TAR_FILE..."
        sudo k3s ctr -n k8s.io images import "$K3S_IMPORT_DIR/$TAR_FILE" > /dev/null
        
        # 3. Find the new digest. We look for the one with the @sha256 suffix
        # which is the "content-addressed" reference created during import.
        NEW_DIGEST=\$(sudo k3s ctr -n k8s.io images list | grep "$APP_NAME" | grep "@sha256" | awk '{print \$1}' | head -n 1)
        
        if [ ! -z "\$NEW_DIGEST" ]; then
            echo "    Found Digest: \$NEW_DIGEST"
            echo "    Applying tag: $FULL_IMAGE_NAME"
            # Explicitly tag the digest as the named ':latest' image
            sudo k3s ctr -n k8s.io images tag "\$NEW_DIGEST" "$FULL_IMAGE_NAME" > /dev/null
        else
            # Fallback: if no digest found, try to tag whatever name appeared
            ANY_REF=\$(sudo k3s ctr -n k8s.io images list -q | grep "$APP_NAME" | head -n 1)
            if [ ! -z "\$ANY_REF" ]; then
                sudo k3s ctr -n k8s.io images tag "\$ANY_REF" "$FULL_IMAGE_NAME" > /dev/null
            else
                echo "    [!] Error: No image found after import on \$IP"
            fi
        fi
EOF
done < "$HOSTS_FILE"

echo "--- [5/5] Verification ---"
# Check the first node in the list as a representative sample
SAMPLE_IP=$(grep -v '^#' "$HOSTS_FILE" | head -n 1)
echo "Checking representative node: $SAMPLE_IP"
# Check both the specific tag and the general list if it fails
REMOTE_INFO=$(ssh -n "$USERNAME@$SAMPLE_IP" "sudo k3s ctr -n k8s.io images list | grep $APP_NAME | grep latest")

if [ ! -z "$REMOTE_INFO" ]; then
    echo "SUCCESS: $APP_NAME updated and explicitly tagged as :latest"
    echo "$REMOTE_INFO"
else
    echo "ERROR: Image tag ':latest' still missing on $SAMPLE_IP."
    echo "Current state of images for $APP_NAME:"
    ssh -n "$USERNAME@$SAMPLE_IP" "sudo k3s ctr -n k8s.io images list | grep $APP_NAME"
fi

# Cleanup local tar
rm "$TAR_FILE"
echo "Done."
