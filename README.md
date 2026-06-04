# cluster_sat

Cluster SAT is a small Kubernetes workload replay tool with a browser dashboard. It reads a CSV of submission timestamps, replays the workload as Kubernetes Jobs, and reports live throughput/latency while preserving the burst pattern in the trace.

## What’s included

- `workload_generator.py` runs the replay from the command line.
- `server.py` serves a frontend and a JSON API for uploads, previews, and live runs.
- `web/` contains the browser UI.
- `set_active_n.sh` labels the subset of nodes used for the benchmark.
- `capacity_sweep.sh` and `node_size_sweep.sh` automate benchmark sweeps.

## Backend + frontend

Start the dashboard:

```bash
python3 server.py --port 8000
```

Open `http://localhost:8000`, paste or upload a CSV, and start a run.

The UI sends the CSV as JSON, so no separate file-upload stack is needed.

## CLI replay

Run the workload directly:

```bash
python3 workload_generator.py --csv path/to/submissions.csv --scale 1.0 --gap-compression-seconds 300
```

Useful options:

- `--scale` speeds up or slows down the trace.
- `--gap-compression-seconds` collapses idle gaps larger than the threshold.
- Without `--csv`, the script falls back to the original concurrency-target mode.

## Helper scripts

- `set_active_n.sh` sets the number of active nodes by applying the `usage=subset` label.
- `helpers/enable_nopasswd.sh` enables passwordless sudo for the `kalm` user.

## Notes

- The replay path expects a kubeconfig or the k3s config at `/etc/rancher/k3s/k3s.yaml`.
- The dashboard uses the same replay logic as the CLI, so preview and execution stay aligned.
