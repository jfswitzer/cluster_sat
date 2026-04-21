#!/bin/bash

# --- Configuration ---
HOSTS_FILE="ips.txt"
USERNAME="kalm"
PLATFORM="linux/arm64"
# The folder where K3s automatically imports images from
K3S_IMPORT_DIR="/var/lib/rancher/k3s/agent/images"

# Image names (using standard naming for K3s compatibility)
APPS=("sort" "primes" "matrix")
TAG_PREFIX="local-grader"

if [ ! -f "$HOSTS_FILE" ]; then
    echo "Error: $HOSTS_FILE not found."
    exit 1
fi

echo "--- 1. Building and Packaging Images (ARM64) ---"

# Function to build and save an image
package_app() {
    local app_name=$1
    local grader_content=$2
    local submission_content=$3
    local full_tag="$TAG_PREFIX-$app_name:latest"
    local tar_file="$TAG_PREFIX-$app_name.tar"

    echo "[*] Preparing build context for $app_name..."
    mkdir -p "build_$app_name"
    
    cat <<EOF > "build_$app_name/Dockerfile"
FROM python:3.11-slim-bullseye
WORKDIR /app
COPY grader.py .
COPY submission.py .
ENTRYPOINT ["python", "grader.py"]
EOF

    echo "$grader_content" > "build_$app_name/grader.py"
    echo "$submission_content" > "build_$app_name/submission.py"

    echo "[*] Building $full_tag for $PLATFORM..."
    # Using buildx to ensure we get the correct architecture for the Pis
    sudo docker buildx build --platform "$PLATFORM" -t "$full_tag" "build_$app_name" --load

    echo "[*] Saving to $tar_file..."
    sudo docker save "$full_tag" > "$tar_file"
    
    # Cleanup build directory
    rm -rf "build_$app_name"
}

# --- App Logic Definitions ---
SORT_GRADER=$(cat <<'EOF'
import time, random, submission
def test_sorting():
    case = [random.randint(0, 1000) for _ in range(5000)]
    start = time.time()
    result = submission.student_sort(case)
    print(f"Sort finished in {time.time() - start:.4f}s")
    return result == sorted(case)
if __name__ == "__main__":
    print("Grade: 100" if test_sorting() else "Grade: 0")
EOF
)
SORT_SUB="def student_sort(arr): return sorted(arr)"

PRIME_GRADER=$(cat <<'EOF'
import time, submission
def test_primes():
    start = time.time()
    res = submission.find_primes(100000)
    print(f"Primes finished in {time.time() - start:.4f}s")
    return len(res) == 9592
if __name__ == "__main__":
    print("Grade: 100" if test_primes() else "Grade: 0")
EOF
)
PRIME_SUB=$(cat <<'EOF'
def find_primes(n):
    is_prime = [True] * (n + 1)
    for p in range(2, int(n**0.5) + 1):
        if is_prime[p]:
            for i in range(p * p, n + 1, p): is_prime[i] = False
    return [p for p in range(2, n + 1) if is_prime[p]]
EOF
)

MATRIX_GRADER=$(cat <<'EOF'
import time, random, submission
def test_matrix():
    size = 200
    m1 = [[random.random() for _ in range(size)] for _ in range(size)]
    m2 = [[random.random() for _ in range(size)] for _ in range(size)]
    start = time.time()
    res = submission.multiply(m1, m2)
    print(f"Matrix finished in {time.time() - start:.4f}s")
    return len(res) == size
if __name__ == "__main__":
    print("Grade: 100" if test_matrix() else "Grade: 0")
EOF
)
MATRIX_SUB=$(cat <<'EOF'
def multiply(A, B):
    size = len(A)
    res = [[0]*size for _ in range(size)]
    for i in range(size):
        for j in range(size):
            for k in range(size):
                res[i][j] += A[i][k] * B[k][j]
    return res
EOF
)

# Run the build process
package_app "sort" "$SORT_GRADER" "$SORT_SUB"
package_app "primes" "$PRIME_GRADER" "$PRIME_SUB"
package_app "matrix" "$MATRIX_GRADER" "$MATRIX_SUB"

echo -e "\n--- 2. Distributing Tarballs to 20 Nodes ---"

while read -r IP || [ -n "$IP" ]; do
    [[ -z "$IP" || "$IP" == \#* ]] && continue
    echo "[*] Node: $IP"

    # Ensure target directory exists
    ssh "$USERNAME@$IP" "sudo mkdir -p $K3S_IMPORT_DIR"

    for APP in "${APPS[@]}"; do
        TAR="$TAG_PREFIX-$APP.tar"
        echo "  [>] Sending $TAR..."
        scp "$TAR" "$USERNAME@$IP:/tmp/$TAR"
        ssh "$USERNAME@$IP" "sudo mv /tmp/$TAR $K3S_IMPORT_DIR/$TAR && sudo chmod 644 $K3S_IMPORT_DIR/$TAR"
    done
    echo "[+] Node $IP updated."
done < "$HOSTS_FILE"

echo -e "\nAll images sideloaded successfully. K3s will import them momentarily."
