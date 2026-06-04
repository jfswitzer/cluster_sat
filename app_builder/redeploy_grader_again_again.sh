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

# --- Environment Check ---
if [ "$EUID" -eq 0 ]; then
    echo "[!] WARNING: You are running as root. This may prevent SSH from finding your user keys."
    echo "    Please run this script as your normal user (e.g., 'baking')."
fi

# --- Password Handling ---
# We ask for the password once locally and pass it to both local and remote sudo calls
echo "Enter sudo password for $USERNAME (used for both local Docker and remote Pi nodes):"
read -sp "> " SUDO_PASS
echo -e "\n"

echo "--- [1/4] Building $APP_NAME for $PLATFORM (NO CACHE) ---"

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

# Build the image locally using sudo with the provided password
echo "$SUDO_PASS" | sudo -S docker buildx build --platform "$PLATFORM" \
    -t "$FULL_IMAGE_NAME" \
    --no-cache \
    "apps/$APP_NAME" --load

if [ $? -ne 0 ]; then echo "Build failed!"; exit 1; fi

echo "--- [2/4] Exporting to Tarball ---"
TAR_FILE="local-grader-$APP_NAME.tar"
# Save the image using sudo
echo "$SUDO_PASS" | sudo -S docker save "$FULL_IMAGE_NAME" > "$TAR_FILE"

# Get the Image ID to verify later
LOCAL_IMAGE_ID=$(echo "$SUDO_PASS" | sudo -S docker images --format "{{.ID}}" "$FULL_IMAGE_NAME")
echo "Local Image ID: $LOCAL_IMAGE_ID"

echo "--- [3/4] Distributing and Processing on 20 Nodes ---"

while read -r IP || [ -n "$IP" ]; do
    [[ -z "$IP" || "$IP" == \#* ]] && continue
    echo "[*] Processing node: $IP"
    
    # We pipe the tarball directly through SSH.
    # Because we are running as a normal user, SSH will find the keys in ~/.ssh/
    cat "$TAR_FILE" | ssh -o ConnectTimeout=10 "$USERNAME@$IP" "
        # 1. Save the piped tarball to /tmp
        cat > /tmp/$TAR_FILE

        # Helper to run sudo commands with the piped password
        run_sudo() {
            echo '$SUDO_PASS' | sudo -S \$@
        }

        # 2. Kill existing pods using the old image
        run_sudo k3s kubectl delete pods -l app-type=$APP_NAME --force --grace-period=0 > /dev/null 2>&1

        # 3. Clean up ALL existing references for this app
        EXISTING_REFS=\$(run_sudo k3s ctr -n k8s.io images list -q | grep '$APP_NAME')
        for ref in \$EXISTING_REFS; do
            run_sudo k3s ctr -n k8s.io images remove \"\$ref\" > /dev/null 2>&1
        done

        # 4. Move file and Manually trigger the import
        run_sudo mv /tmp/$TAR_FILE $K3S_IMPORT_DIR/$TAR_FILE
        run_sudo k3s ctr -n k8s.io images import '$K3S_IMPORT_DIR/$TAR_FILE' > /dev/null
        
        # 5. Find the RAW SHA256 digest and force-apply tags
        NEW_SHA=\$(run_sudo k3s ctr -n k8s.io images list | grep '$APP_NAME' | grep -o 'sha256:[a-f0-9]\{64\}' | head -n 1)
        
        if [ ! -z \"\$NEW_SHA\" ]; then
            echo '    Found Digest: '\"\$NEW_SHA\"
            run_sudo k3s ctr -n k8s.io images tag \"\$NEW_SHA\" '$FULL_IMAGE_NAME' > /dev/null
            run_sudo k3s ctr -n k8s.io images tag \"\$NEW_SHA\" 'local-grader-$APP_NAME:latest' > /dev/null
        else
            echo '    [!] Error: Could not find digest for $APP_NAME on $IP'
        fi
    "
done < "$HOSTS_FILE"

echo "--- [4/4] Final Cluster Verification ---"
SAMPLE_IP=$(grep -v '^#' "$HOSTS_FILE" | head -n 1)
echo "Checking representative node: $SAMPLE_IP"
REMOTE_INFO=$(ssh -n "$USERNAME@$SAMPLE_IP" "echo '$SUDO_PASS' | sudo -S k3s ctr -n k8s.io images list | grep $APP_NAME | grep latest")

if [ ! -z "$REMOTE_INFO" ]; then
    echo "SUCCESS: $APP_NAME updated and explicitly tagged as :latest"
    echo "New Image Info: $REMOTE_INFO"
else
    echo "ERROR: Image tag ':latest' still missing on $SAMPLE_IP."
fi

# Cleanup
rm "$TAR_FILE"
echo "Done. All nodes processed using single-password-entry flow."
