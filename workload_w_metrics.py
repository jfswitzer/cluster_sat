import subprocess
import yaml
import time
import json
from collections import defaultdict
import sys

# --- Configuration ---
if len(sys.argv)>1:
    CONCURRENCY_TARGET=int(sys.argv[1])
else:
    CONCURRENCY_TARGET=40

TEST_DURATION = 300      # Test duration in seconds
APP_TYPES = ["sort", "primes", "matrix"]
NAMESPACE = "default"

# --- State Tracking ---
metrics = {
    "total_completed": 0,
    "latencies": defaultdict(list),
    "errors": 0,
    "start_time": None
}

# --- Job Template ---
def get_job_yaml(app_type, job_id):
    # We use "active" instead of "true" because K8s labels must be strings.
    # YAML parsers often convert the word 'true' into a boolean, causing an error.
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"bench-{app_type}-{job_id}",
            "labels": {
                "benchmark": "active", 
                "app-type": str(app_type)
            }
        },
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": "grader",
                        "image": f"local-grader-{app_type}:latest",
                        "imagePullPolicy": "IfNotPresent",
                        "resources": {
                            "requests": {"cpu": "200m", "memory": "128Mi"},
                            "limits": {"cpu": "500m", "memory": "256Mi"}
                        }
                    }],
                    "restartPolicy": "Never"
                }
            },
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 10
        }
    }

def run_command(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode('utf-8')
    except subprocess.CalledProcessError as e:
        # Don't crash on minor API errors
        return ""

def submit_job(app_type):
    job_id = int(time.time() * 1000) % 1000000
    job_yaml = get_job_yaml(app_type, job_id)
    submit_time = time.time()
    
    # Explicitly dump and pipe to kubectl
    yaml_data = yaml.dump(job_yaml)
    process = subprocess.Popen(['kubectl', 'apply', '-f', '-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    process.communicate(input=yaml_data)
    
    return f"bench-{app_type}-{job_id}", submit_time, app_type

def monitor_and_measure():
    print(f"--- Starting Benchmark: Concurrency={CONCURRENCY_TARGET}, Duration={TEST_DURATION}s ---")
    metrics["start_time"] = time.time()
    active_jobs = {} # name -> (start_time, type)
    
    try:
        while time.time() - metrics["start_time"] < TEST_DURATION:
            # 1. Check status of existing jobs
            if active_jobs:
                # Filter by the "benchmark=active" label
                job_list_json = run_command("kubectl get jobs -l benchmark=active -o json")
                if job_list_json:
                    try:
                        data = json.loads(job_list_json)
                        items = data.get('items', [])
                        
                        finished = []
                        for name, (start_t, app_t) in active_jobs.items():
                            job_data = next((item for item in items if item['metadata']['name'] == name), None)
                            
                            if job_data:
                                status = job_data.get('status', {})
                                if status.get('succeeded'):
                                    latency = time.time() - start_t
                                    metrics["latencies"][app_t].append(latency)
                                    metrics["total_completed"] += 1
                                    finished.append(name)
                                elif status.get('failed'):
                                    metrics["errors"] += 1
                                    finished.append(name)
                            else:
                                # Job potentially already cleaned up by TTL
                                finished.append(name)

                        for name in finished:
                            del active_jobs[name]
                    except json.JSONDecodeError:
                        pass

            # 2. Refill the pipeline
            while len(active_jobs) < CONCURRENCY_TARGET:
                import random
                app_choice = random.choice(APP_TYPES)
                name, start_t, app_t = submit_job(app_choice)
                active_jobs[name] = (start_t, app_t)
            
            elapsed = time.time() - metrics["start_time"]
            throughput = metrics["total_completed"] / elapsed if elapsed > 0 else 0
            print(f"Elapsed: {int(elapsed)}s | Active: {len(active_jobs)} | Done: {metrics['total_completed']} | TPS: {throughput:.2f} j/s", end='\r')
            time.sleep(1.5) # Slightly slower poll to be kind to the API

    except KeyboardInterrupt:
        print("\nBenchmark interrupted.")

    finalize_metrics()

def finalize_metrics():
    total_time = time.time() - metrics["start_time"]
    total_jobs = metrics["total_completed"]
    overall_throughput = total_jobs / total_time
    
    print("\n\n" + "="*45)
    print("      BENCHMARK RESULTS (MIXED WORKLOAD)")
    print("="*45)
    print(f"Total Duration:    {total_time:.2f}s")
    print(f"Total Successful:  {total_jobs}")
    print(f"Total Failed:      {metrics['errors']}")
    print(f"Overall Throughput: {overall_throughput:.2f} jobs/s")
    print("-" * 45)
    print(f"{'App Type':<12} | {'Avg Latency':<12} | {'P95 (s)':<8}")
    print("-" * 45)
    
    for app in APP_TYPES:
        lats = sorted(metrics["latencies"][app])
        if lats:
            avg = sum(lats) / len(lats)
            p95 = lats[int(len(lats) * 0.95)]
            print(f"{app:<12} | {avg:<12.2f} | {p95:<8.2f}")
        else:
            print(f"{app:<12} | {'N/A':<12} | {'N/A':<8}")
    print("="*45)
    
    print("Cleaning up benchmark jobs...")
    subprocess.run("kubectl delete jobs -l benchmark=active", shell=True)

if __name__ == "__main__":
    monitor_and_measure()
