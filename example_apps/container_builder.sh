#!/bin/bash

# --- Configuration ---
# Set REGISTRY to the Node IP and Port 30500 from your local-registry.yaml
# Use any node IP in your cluster or 127.0.0.1 if building on a cluster node.
REGISTRY="10.0.0.1:30500" 
PLATFORM="linux/arm64"
NAMESPACE="k8s.io" # Standard namespace for K3s/containerd images

# Verify nerdctl is installed
if ! command -v nerdctl &> /dev/null; then
    echo "Error: nerdctl not found. Please install nerdctl and buildkitd."
    exit 1
fi

echo "--- Starting Build Process for ARM64 Images (containerd/nerdctl) ---"

# Function to create and build an app
build_app() {
    local app_name=$1
    local grader_content=$2
    local submission_content=$3
    local image_tag="$REGISTRY/grader-$app_name:latest"

    echo "[*] Preparing $app_name..."
    mkdir -p "build_$app_name"
    
    # Write Dockerfile
    cat <<EOF > "build_$app_name/Dockerfile"
FROM python:3.11-slim-bullseye
WORKDIR /app
COPY grader.py .
COPY submission.py .
ENTRYPOINT ["python", "grader.py"]
EOF

    # Write Grader and Submission files
    echo "$grader_content" > "build_$app_name/grader.py"
    echo "$submission_content" > "build_$app_name/submission.py"

    echo "[*] Building $image_tag..."
    # nerdctl build requires buildkitd to be running.
    # We specify the namespace so images are visible to the K3s runtime.
    sudo nerdctl -n "$NAMESPACE" build \
        --platform "$PLATFORM" \
        -t "$image_tag" \
        "build_$app_name"

    echo "[*] Pushing to insecure registry at $REGISTRY..."
    # We must explicitly allow the insecure (HTTP) registry for the local NodePort
    sudo nerdctl -n "$NAMESPACE" push "$image_tag" --insecure-registry

    echo "[+] Done with $app_name"
    echo "-----------------------------------"
}

# --- Workload Logic ---

# APP 1: SORT (Light)
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
SORT_SUBMISSION="def student_sort(arr): return sorted(arr)"

# APP 2: PRIMES (Medium)
PRIME_GRADER=$(cat <<'EOF'
import time, submission
def test_primes():
    start = time.time()
    res = submission.find_primes(1000000)
    print(f"Primes finished in {time.time() - start:.4f}s")
    return len(res) == 78498
if __name__ == "__main__":
    print("Grade: 100" if test_primes() else "Grade: 0")
EOF
)
PRIME_SUBMISSION=$(cat <<'EOF'
def find_primes(n):
    is_prime = [True] * (n + 1)
    for p in range(2, int(n**0.5) + 1):
        if is_prime[p]:
            for i in range(p * p, n + 1, p): is_prime[i] = False
    return [p for p in range(2, n + 1) if is_prime[p]]
EOF
)

# APP 3: MATRIX (Heavy)
MATRIX_GRADER=$(cat <<'EOF'
import time, random, submission
def test_matrix():
    size = 400
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
MATRIX_SUBMISSION=$(cat <<'EOF'
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

# Execute Builds
build_app "sort" "$SORT_GRADER" "$SORT_SUBMISSION"
build_app "primes" "$PRIME_GRADER" "$PRIME_SUBMISSION"
build_app "matrix" "$MATRIX_GRADER" "$MATRIX_SUBMISSION"

echo "!!! All images built and pushed for ARM64 via nerdctl !!!"
