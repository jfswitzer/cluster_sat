from __future__ import annotations

import argparse
from kubernetes import client, config
import csv
import io
import json
import os
import random
import subprocess
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CONCURRENCY_TARGET = 80
DEFAULT_TEST_DURATION = 300
DEFAULT_SUBMISSION_WORKERS = 20
DEFAULT_GAP_COMPRESSION_SECONDS = 300
DEFAULT_APP_TYPES = ["matrix_small"]
# Images for different graders
SMALL_IMAGE = "docker.io/library/local-grader-matrix-small:latest"
ERROR_IMAGE = "docker.io/library/local-grader-matrix-error:latest"
# Default image used when app_type doesn't map explicitly
DEFAULT_IMAGE = SMALL_IMAGE
DEFAULT_NAMESPACE = "default"


def parse_csv_text(csv_text: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    return [dict(row) for row in reader]


def _parse_submission_time(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def build_replay_schedule(
    csv_text: str,
    scale: float = 1.0,
    gap_compression_seconds: int = DEFAULT_GAP_COMPRESSION_SECONDS,
) -> List[Dict[str, Any]]:
    rows = parse_csv_text(csv_text)
    parsed_rows: List[Dict[str, Any]] = []

    for row in rows:
        active = (row.get("active", "") or "").strip().upper()
        if active and active != "TRUE":
            continue

        parsed_time = _parse_submission_time(row.get("submission_time", ""))
        if not parsed_time:
            continue

        parsed_rows.append({**row, "_submission_dt": parsed_time})

    parsed_rows.sort(key=lambda item: item["_submission_dt"])
    if not parsed_rows:
        return []

    compressed: List[Dict[str, Any]] = []
    virtual_time = 0.0
    previous_time = parsed_rows[0]["_submission_dt"]

    for index, row in enumerate(parsed_rows):
        current_time = row["_submission_dt"]
        if index > 0:
            real_gap = (current_time - previous_time).total_seconds()
            if real_gap <= gap_compression_seconds:
                virtual_time += real_gap / max(scale, 1e-9)
        compressed.append(
            {
                "attempt_number": row.get("attempt_number", ""),
                "submission_time": current_time.isoformat(),
                "runtime_ms": row.get("runtime_ms", ""),
                "score": row.get("score", ""),
                "active": row.get("active", ""),
                "offset_s": round(virtual_time, 6),
            }
        )
        previous_time = current_time

    return compressed


def preview_csv(csv_text: str, scale: float = 1.0, gap_compression_seconds: int = DEFAULT_GAP_COMPRESSION_SECONDS) -> Dict[str, Any]:
    rows = parse_csv_text(csv_text)
    schedule = build_replay_schedule(csv_text, scale=scale, gap_compression_seconds=gap_compression_seconds)

    first_submission = None
    last_submission = None
    active_rows = 0
    skipped_rows = 0
    for row in rows:
        active = (row.get("active", "") or "").strip().upper()
        if active and active != "TRUE":
            skipped_rows += 1
            continue
        parsed = _parse_submission_time(row.get("submission_time", ""))
        if not parsed:
            skipped_rows += 1
            continue
        active_rows += 1
        if first_submission is None:
            first_submission = parsed.isoformat()
        last_submission = parsed.isoformat()

    compressed_duration = schedule[-1]["offset_s"] if schedule else 0.0

    return {
        "rows_total": len(rows),
        "rows_active": active_rows,
        "rows_skipped": skipped_rows,
        "first_submission": first_submission,
        "last_submission": last_submission,
        "compressed_duration_s": compressed_duration,
        "schedule_preview": schedule[:10],
        "schedule_total": len(schedule),
    }


class BenchmarkRunner:
    def __init__(
        self,
        *,
        csv_text: Optional[str] = None,
        concurrency_target: int = DEFAULT_CONCURRENCY_TARGET,
        test_duration: int = DEFAULT_TEST_DURATION,
        scale: float = 1.0,
        gap_compression_seconds: int = DEFAULT_GAP_COMPRESSION_SECONDS,
        submission_workers: int = DEFAULT_SUBMISSION_WORKERS,
        app_types: Optional[List[str]] = None,
    ) -> None:
        self.concurrency_target = concurrency_target
        self.test_duration = test_duration
        self.scale = scale
        self.gap_compression_seconds = gap_compression_seconds
        self.submission_workers = submission_workers
        self.app_types = app_types or list(DEFAULT_APP_TYPES)
        self.csv_text = csv_text
        self.schedule = build_replay_schedule(
            csv_text, scale=scale, gap_compression_seconds=gap_compression_seconds
        ) if csv_text else []
        self.mode = "replay" if self.schedule else "concurrency"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._batch_v1: Any = None
        self._client: Any = None
        self._started_at: Optional[float] = None
        self._finished_at: Optional[float] = None
        self._status = "pending"
        self._error: Optional[str] = None
        self._replayed_index = 0
        self.active_jobs: Dict[str, Any] = {}
        self.metrics = {
            "total_completed": 0,
            "latencies": defaultdict(list),
            "schedule_latencies": defaultdict(list),
            "errors": 0,
            "start_time": None,
            "completion_window": deque(),
            "submitted": 0,
            # recent completion events for time-series graphs
            "completions": deque(maxlen=10000),
        }
        self.recent_events = deque(maxlen=50)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="benchmark-runner", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._stop_event.set()

    def _record_event(self, kind: str, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "ts": time.time(),
            "kind": kind,
            "message": message,
        }
        if extra:
            payload.update(extra)
        with self._lock:
            self.recent_events.append(payload)

    def _get_job_object(self, client, app_type: str, job_id: int, image_override: Optional[str] = None):
        container = client.V1Container(
            name="grader",
            image=(image_override or (SMALL_IMAGE if app_type == "matrix_small" else (ERROR_IMAGE if app_type == "matrix_error" else DEFAULT_IMAGE))),
            image_pull_policy="IfNotPresent",
        )
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels={"app": "bench"}),
            spec=client.V1PodSpec(
                node_selector={"usage": "subset"},
                restart_policy="Never",
                containers=[container],
                automount_service_account_token=False,
            ),
        )
        return client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=f"b-{job_id}", labels={"benchmark": "active"}),
            spec=client.V1JobSpec(template=template, backoff_limit=0, ttl_seconds_after_finished=60),
        )

    def _submit_job_task(self, app_type: str, planned_offset: Optional[float] = None):
        job_id = int(time.time() * 1000000) % 10000000
        job_obj = self._get_job_object(self._client, app_type, job_id)
        start_t = time.time()
        try:
            self._batch_v1.create_namespaced_job(namespace=DEFAULT_NAMESPACE, body=job_obj)
            return f"b-{job_id}", start_t, app_type, planned_offset
        except Exception as exc:
            # If submission failed, attempt to schedule a job that uses the erroring grader image
            self._record_event("submit_error", "failed to create job, attempting error-image fallback", {"error": str(exc)})
            try:
                fallback_obj = self._get_job_object(self._client, app_type, job_id, image_override=ERROR_IMAGE)
                self._batch_v1.create_namespaced_job(namespace=DEFAULT_NAMESPACE, body=fallback_obj)
                self._record_event("submit_fallback", "submitted error-image fallback job", {"job": f"b-{job_id}"})
                return f"b-{job_id}", start_t, app_type, planned_offset
            except Exception as exc2:
                self._record_event("submit_error", "fallback submission also failed", {"error": str(exc2)})
                return None, None, None, None

    def _poll_status(self) -> None:
        jobs = self._batch_v1.list_namespaced_job(namespace=DEFAULT_NAMESPACE, label_selector="benchmark=active")
        current_items = {job.metadata.name: job.status for job in jobs.items}

        finished = []
        with self._lock:
            tracked = list(self.active_jobs.items())

        for name, (start_t, app_t, planned_offset) in tracked:
            status = current_items.get(name)
            if status:
                # Some k8s clients expose `succeeded` while others set a Complete condition.
                succeeded = getattr(status, "succeeded", None)
                failed = getattr(status, "failed", None)
                complete_condition = False
                if getattr(status, "conditions", None):
                    for c in status.conditions:
                        if getattr(c, "type", "") == "Complete" and getattr(c, "status", "") == "True":
                            complete_condition = True

                if succeeded or complete_condition:
                    latency = time.time() - start_t
                    with self._lock:
                        self.metrics["latencies"][app_t].append(latency)
                        self.metrics["total_completed"] += 1
                        self.metrics["completion_window"].append(time.time())
                        # record completion event for time-series graphs
                        self.metrics["completions"].append({"ts": time.time(), "latency": latency, "app": app_t})
                        # If we have a planned offset (replay mode), record time from scheduled arrival
                        if planned_offset is not None and self._started_at is not None:
                            schedule_latency = time.time() - (self._started_at + planned_offset)
                            self.metrics["schedule_latencies"][app_t].append(schedule_latency)
                    finished.append(name)
                elif failed:
                    with self._lock:
                        self.metrics["errors"] += 1
                    finished.append(name)
            elif name not in current_items:
                finished.append(name)

        if finished:
            with self._lock:
                for name in finished:
                    self.active_jobs.pop(name, None)

    def _run(self) -> None:
        self._status = "running"
        self._started_at = time.time()
        self.metrics["start_time"] = self._started_at

        try:
            # Load kube config from the environment (KUBECONFIG or ~/.kube/config).
            # Fall back to in-cluster config if running inside a cluster.
            try:
                config.load_kube_config()
            except Exception:
                config.load_incluster_config()

            # Use the kubernetes client module directly
            self._client = client
            self._batch_v1 = client.BatchV1Api()
        except Exception as exc:
            self._status = "failed"
            self._error = str(exc)
            self._finished_at = time.time()
            self._record_event("startup_error", "failed to initialize Kubernetes client", {"error": self._error})
            return

        run_duration = self.test_duration
        if self.schedule:
            run_duration = self.schedule[-1]["offset_s"] + 30.0

        self._record_event("start", "benchmark run started", {"mode": self.mode, "schedule_total": len(self.schedule)})

        with ThreadPoolExecutor(max_workers=self.submission_workers) as executor:
            try:
                schedule_index = 0
                while not self._stop_event.is_set() and (time.time() - self._started_at) < run_duration:
                    try:
                        self._poll_status()
                    except Exception as exc:
                        self._record_event("poll_error", "failed to poll job status", {"error": str(exc)})

                    if self.schedule:
                        elapsed = time.time() - self._started_at
                        to_submit = 0
                        while schedule_index < len(self.schedule) and self.schedule[schedule_index]["offset_s"] <= elapsed:
                            to_submit += 1
                            schedule_index += 1
                        with self._lock:
                            self._replayed_index = schedule_index

                        if to_submit > 0:
                                    # Determine which schedule entries we're submitting now
                                    first_idx = schedule_index - to_submit
                                    planned_offsets = [self.schedule[i]["offset_s"] for i in range(first_idx, schedule_index)]
                                    futures = [executor.submit(self._submit_job_task, random.choice(self.app_types), planned_offsets[i]) for i in range(len(planned_offsets))]
                                    for future in futures:
                                        name, start_t, app_t, planned_offset = future.result()
                                        if name:
                                            with self._lock:
                                                self.active_jobs[name] = (start_t, app_t, planned_offset)
                                                self.metrics["submitted"] += 1
                    else:
                        with self._lock:
                            needed = self.concurrency_target - len(self.active_jobs)

                        if needed > 0:
                            num_to_submit = min(needed, self.submission_workers)
                            futures = [executor.submit(self._submit_job_task, random.choice(self.app_types), None) for _ in range(num_to_submit)]
                            for future in futures:
                                name, start_t, app_t, _ = future.result()
                                if name:
                                    with self._lock:
                                        self.active_jobs[name] = (start_t, app_t, None)
                                        self.metrics["submitted"] += 1

                    time.sleep(0.5)

                # After main submission loop exits, give in-flight jobs a short grace period
                # so their completions are observed and recorded before we mark the run finished.
                if self._stop_event.is_set():
                    self._status = "cancelled"
                else:
                    grace_seconds = 500.0
                    end_wait = time.time() + grace_seconds
                    # Poll until active jobs clear or timeout
                    while time.time() < end_wait and self.active_jobs and not self._stop_event.is_set():
                        try:
                            self._poll_status()
                        except Exception as exc:
                            self._record_event("poll_error", "failed to poll job status during grace period", {"error": str(exc)})
                        time.sleep(0.5)
                    self._status = "completed" if not self._stop_event.is_set() else "cancelled"
            except KeyboardInterrupt:
                self._status = "cancelled"
                self._record_event("cancelled", "run interrupted by user")
            except Exception as exc:
                self._status = "failed"
                self._error = str(exc)
                self._record_event("runtime_error", "benchmark run failed", {"error": self._error})
            finally:
                self._finished_at = time.time()
                self._cleanup_jobs()
                self._record_event("finished", "benchmark run finished", {"status": self._status})

    def _cleanup_jobs(self) -> None:
        try:
            subprocess.run("kubectl delete jobs -l benchmark=active", shell=True, check=False)
        except Exception:
            pass

    def _latency_stats(self) -> Dict[str, Dict[str, float]]:
        stats: Dict[str, Dict[str, float]] = {}
        for app in self.app_types:
            values = sorted(self.metrics["latencies"][app])
            if not values:
                continue
            p95_index = min(len(values) - 1, int(len(values) * 0.95))
            stats[app] = {
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
                "p95": values[p95_index],
                "count": len(values),
            }
        return stats

    def _completion_stats(self) -> Dict[str, float]:
        # overall completion latency stats (across apps)
        all_vals = [c["latency"] for c in list(self.metrics["completions"]) ]
        if not all_vals:
            return {"avg": 0.0, "min": 0.0, "max": 0.0, "p95": 0.0, "count": 0}
        vals = sorted(all_vals)
        p95_index = min(len(vals) - 1, int(len(vals) * 0.95))
        return {
            "avg": sum(vals) / len(vals),
            "min": vals[0],
            "max": vals[-1],
            "p95": vals[p95_index],
            "count": len(vals),
        }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            started = self._started_at or now
            elapsed = now - started if self._started_at else 0.0
            avg_tps = self.metrics["total_completed"] / elapsed if elapsed > 0 else 0.0
            return {
                "status": self._status,
                "error": self._error,
                "mode": self.mode,
                "config": {
                    "concurrency_target": self.concurrency_target,
                    "test_duration": self.test_duration,
                    "scale": self.scale,
                    "gap_compression_seconds": self.gap_compression_seconds,
                    "submission_workers": self.submission_workers,
                    "app_types": list(self.app_types),
                },
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "elapsed_s": elapsed,
                "metrics": {
                    "submitted": self.metrics["submitted"],
                    "completed": self.metrics["total_completed"],
                    "errors": self.metrics["errors"],
                    "active_jobs": len(self.active_jobs),
                    "avg_tps": avg_tps,
                    "completion_window_size": len(self.metrics["completion_window"]),
                },
                "schedule": {
                    "total": len(self.schedule),
                    "replayed_index": self._replayed_index,
                    "compressed_duration_s": self.schedule[-1]["offset_s"] if self.schedule else 0.0,
                },
                "latency_stats": self._latency_stats(),
                "completion_stats": self._completion_stats(),
                "completions": list(self.metrics["completions"]),
                "recent_events": list(self.recent_events),
            }


def run_cli(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Kubernetes workload generator")
    parser.add_argument("concurrency", nargs="?", type=int, default=DEFAULT_CONCURRENCY_TARGET,
                        help="Number of jobs to keep active (ignored in replay mode)")
    parser.add_argument("--csv", dest="csvfile", default=None,
                        help="Path to CSV file to replay")
    parser.add_argument("--scale", dest="scale", type=float, default=1.0,
                        help="Time scale for replay: 1.0 = real time, 2.0 = 2x faster")
    parser.add_argument("--gap-compression-seconds", dest="gap_compression_seconds", type=int,
                        default=DEFAULT_GAP_COMPRESSION_SECONDS,
                        help="Gap size that gets collapsed to zero in replay mode")
    parser.add_argument("--duration", dest="duration", type=int, default=DEFAULT_TEST_DURATION,
                        help="Test duration in seconds (used if no CSV replay)")
    args = parser.parse_args(argv)

    csv_text = None
    if args.csvfile:
        csv_text = Path(args.csvfile).read_text()

    runner = BenchmarkRunner(
        csv_text=csv_text,
        concurrency_target=args.concurrency,
        test_duration=args.duration,
        scale=args.scale,
        gap_compression_seconds=args.gap_compression_seconds,
        submission_workers=DEFAULT_SUBMISSION_WORKERS,
        app_types=DEFAULT_APP_TYPES,
    )
    runner.start()
    if runner._thread:
        runner._thread.join()

    snapshot = runner.snapshot()
    print("\n\n" + "=" * 60)
    print("      FINAL PERFORMANCE REPORT")
    print("=" * 60)
    print(f"Status: {snapshot['status']}")
    print(f"Overall Throughput: {snapshot['metrics']['avg_tps']:.2f} jobs/s")
    print("-" * 60)
    print(f"{'App Type':<12} | {'Avg':<8} | {'Min':<8} | {'Max':<8} | {'P95 (s)':<8}")
    for app, stats in snapshot["latency_stats"].items():
        print(f"{app:<12} | {stats['avg']:<8.2f} | {stats['min']:<8.2f} | {stats['max']:<8.2f} | {stats['p95']:<8.2f}")
    print("=" * 60)


if __name__ == "__main__":
    run_cli()