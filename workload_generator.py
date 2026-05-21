import time
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import subprocess
import sys
# --- Configuration ---
if len(sys.argv)>1:
    CONCURRENCY_TARGET = int(sys.argv[1])  # Number of jobs to keep active
else:
    CONCURRENCY_TARGET = 80
TEST_DURATION = 300       # Seconds
#APP_TYPES = ["sort", "primes", "matrix"]
APP_TYPES=["matrix"]
SUBMISSION_WORKERS = 20   # Maximum parallel API calls

def load_kubernetes_config():
    try:
        config.load_kube_config()
    except Exception:
        k3s_config = "/etc/rancher/k3s/k3s.yaml"
        if os.path.exists(k3s_config):
            config.load_kube_config(config_file=k3s_config)
        else:
            print("Error: No Kubeconfig found. Try: export KUBECONFIG=/etc/rancher/k3s/k3s.yaml")
            exit(1)

load_kubernetes_config()
batch_v1 = client.BatchV1Api()

# Metrics storage
metrics = {
    "total_completed": 0, 
    "latencies": defaultdict(list), 
    "errors": 0, 
    "start_time": None
}
active_jobs = {} # name -> (start_t, app_t)

def get_job_object(app_type, job_id):
    """Creates a minimal Job object to reduce API/DB overhead."""
    container = client.V1Container(
        name="grader",
        image=f"docker.io/library/local-grader-matrix:latest",
        image_pull_policy="IfNotPresent",
    )
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": "bench"}),
        spec=client.V1PodSpec(
            node_selector={"usage": "subset"},
            restart_policy="Never", 
            containers=[container],
            automount_service_account_token=False 
        )
    )
    return client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=f"b-{job_id}", labels={"benchmark": "active"}),
        spec=client.V1JobSpec(template=template, backoff_limit=0, ttl_seconds_after_finished=60)
    )

def submit_job_task(app_type):
    """Submits a single job to the API."""
    job_id = int(time.time() * 1000000) % 10000000
    job_obj = get_job_object(app_type, job_id)
    start_t = time.time()
    try:
        batch_v1.create_namespaced_job(namespace="default", body=job_obj)
        return f"b-{job_id}", start_t, app_type
    except Exception:
        return None, None, None

def monitor_and_measure():
    print(f"--- Decoupled Parallel Benchmark: Target={CONCURRENCY_TARGET} ---")
    metrics["start_time"] = time.time()
    
    with ThreadPoolExecutor(max_workers=SUBMISSION_WORKERS) as executor:
        try:
            while time.time() - metrics["start_time"] < TEST_DURATION:
                # 1. Non-blocking Status Update
                try:
                    # List only the essential fields to reduce network/parsing time
                    jobs = batch_v1.list_namespaced_job(
                        namespace="default", 
                        label_selector="benchmark=active",
                        _continue=None
                    )
                    current_items = {j.metadata.name: j.status for j in jobs.items}
                    
                    finished = []
                    for name, (start_t, app_t) in list(active_jobs.items()):
                        status = current_items.get(name)
                        if status:
                            if status.succeeded:
                                latency = time.time() - start_t
                                metrics["latencies"][app_t].append(latency)
                                metrics["total_completed"] += 1
                                finished.append(name)
                            elif status.failed:
                                metrics["errors"] += 1
                                finished.append(name)
                        elif name not in current_items:
                            # Job likely finished and was cleaned up by TTL
                            finished.append(name)
                    
                    for n in finished:
                        if n in active_jobs: del active_jobs[n]
                except Exception:
                    pass

                # 2. Parallel Submission (Non-blocking)
                needed = CONCURRENCY_TARGET - len(active_jobs)
                if needed > 0:
                    import random
                    # We don't wait for .result() here anymore. 
                    # We just fire the threads and handle results in the next loop.
                    num_to_submit = min(needed, SUBMISSION_WORKERS)
                    futures = [executor.submit(submit_job_task, random.choice(APP_TYPES)) for _ in range(num_to_submit)]
                    
                    for f in futures:
                        # We still need to grab the name to track it, but the threads 
                        # are already running in parallel.
                        name, start_t, app_t = f.result() 
                        if name:
                            active_jobs[name] = (start_t, app_t)
                
                elapsed = time.time() - metrics["start_time"]
                tps = metrics["total_completed"] / elapsed if elapsed > 0 else 0
                print(f"Elapsed: {int(elapsed)}s | Active: {len(active_jobs)} | Total: {metrics['total_completed']} | TPS: {tps:.2f} j/s", end='\r')
                
                # Slower poll to reduce Master CPU contention during the "Database Wall"
                time.sleep(0.5)

        except KeyboardInterrupt:
            print("\nStopping...")

    finalize_metrics()

def finalize_metrics():
    total_time = time.time() - metrics["start_time"]
    total_jobs = metrics["total_completed"]
    print("\n\n" + "="*60)
    print("      FINAL PERFORMANCE REPORT")
    print("="*60)
    print(f"Overall Throughput: {total_jobs / total_time:.2f} jobs/s")
    print("-" * 60)
    print(f"{'App Type':<12} | {'Avg':<8} | {'Min':<8} | {'Max':<8} | {'P95 (s)':<8}")
    for app in APP_TYPES:
        lats = sorted(metrics["latencies"][app])
        if lats:
            avg, p95 = sum(lats)/len(lats), lats[int(len(lats)*0.95)]
            print(f"{app:<12} | {avg:<8.2f} | {min(lats):<8.2f} | {max(lats):<8.2f} | {p95:<8.2f}")
    print("="*60)
    # Cleanup
    subprocess.run("kubectl delete jobs -l benchmark=active", shell=True)

if __name__ == "__main__":
    monitor_and_measure()
