import subprocess
import os
import time
import yaml
import json

# --- Configuration ---
MANIFESTS_FOLDER = "./example_apps"  # Your folder of .yaml or .json files
NAMESPACE = "load-test-env"
WAVE_SIZE = 10                       # How many jobs to add per wave
COOLDOWN_SECONDS = 30                # Wait for scheduler to react
MAX_PENDING_THRESHOLD = 5            # Stop if more than 5 pods are stuck Pending
TARGET_ARCH = "arm64"                # Force targeting ARM nodes

def run_command(cmd):
    """Executes a shell command and returns the output."""
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return None
    return result.stdout

def get_cluster_status():
    """Checks for Pending pods, Node pressure, and Architecture mismatches."""
    pod_data = run_command(f"kubectl get pods -n {NAMESPACE} -o json")
    if not pod_data: return True, 0, 0
    
    pods = json.loads(pod_data).get('items', [])
    pending_count = sum(1 for p in pods if p.get('status', {}).get('phase') == 'Pending')
    
    # Check for Error states (often 'Exec format error' on ARM)
    error_count = 0
    for p in pods:
        container_statuses = p.get('status', {}).get('containerStatuses', [])
        for status in container_statuses:
            state = status.get('state', {})
            if 'waiting' in state:
                reason = state['waiting'].get('reason', '')
                if reason in ['CrashLoopBackOff', 'ImagePullBackOff', 'ErrImagePull']:
                    error_count += 1
    
    # Check node conditions
    node_data = run_command("kubectl get nodes -o json")
    nodes = json.loads(node_data).get('items', [])
    pressured_nodes = 0
    for node in nodes:
        conditions = node.get('status', {}).get('conditions', [])
        for c in conditions:
            # ARM nodes (like PIs) often saturate on DiskPressure (SD Card I/O)
            if c['type'] in ['MemoryPressure', 'DiskPressure'] and c['status'] == 'True':
                pressured_nodes += 1
                
    return pressured_nodes > 0, pending_count, error_count

def inject_arm_affinity(data):
    """Injects nodeSelector to ensure the job lands on ARM nodes."""
    # Handle both Pods and Controllers (Deployments, Jobs)
    spec = data.get('spec', {})
    if 'template' in spec: # Deployment/Job
        pod_spec = spec['template'].get('spec', {})
    else: # Naked Pod
        pod_spec = spec

    if 'nodeSelector' not in pod_spec:
        pod_spec['nodeSelector'] = {}
    
    pod_spec['nodeSelector']['kubernetes.io/arch'] = TARGET_ARCH
    return data

def deploy_wave(wave_num):
    """Picks a random manifest from the folder and deploys a wave."""
    manifests = [f for f in os.listdir(MANIFESTS_FOLDER) if f.endswith(('.yaml', '.yml'))]
    if not manifests:
        print("No manifests found!")
        return False

    print(f"\n[Wave {wave_num}] Deploying {WAVE_SIZE} new ARM-targeted jobs...")
    for i in range(WAVE_SIZE):
        target = os.path.join(MANIFESTS_FOLDER, manifests[i % len(manifests)])
        job_name = f"arm-load-{wave_num}-{i}"
        
        with open(target, 'r') as f:
            try:
                data = yaml.safe_load(f)
                data['metadata']['name'] = job_name
                # Ensure the job targets ARM
                data = inject_arm_affinity(data)
            except Exception as e:
                print(f"Failed to parse {target}: {e}")
                continue
            
        with open("temp_deploy.yaml", "w") as f:
            yaml.dump(data, f)
            
        run_command(f"kubectl apply -f temp_deploy.yaml -n {NAMESPACE}")
    return True

def main():
    run_command(f"kubectl create namespace {NAMESPACE}")
    
    wave = 1
    while True:
        is_pressured, pending, errors = get_cluster_status()
        
        print(f"Status: {pending} pending, {errors} errors. Pressure: {is_pressured}")
        
        if errors > (WAVE_SIZE // 2):
            print("\n!!! ARCHITECTURE ERROR DETECTED !!!")
            print("Many pods are failing. Check if your images are built for arm64.")
            break

        if pending > MAX_PENDING_THRESHOLD or is_pressured:
            print("\n!!! SATURATION REACHED !!!")
            print(f"Cluster saturated at Wave {wave-1}.")
            while True: time.sleep(10)
            
        if not deploy_wave(wave):
            break
            
        print(f"Waiting {COOLDOWN_SECONDS}s for ARM scheduler...")
        time.sleep(COOLDOWN_SECONDS)
        wave += 1

if __name__ == "__main__":
    main()
