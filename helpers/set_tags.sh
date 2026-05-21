#!/bin/bash
while read -r IP || [ -n "$IP" ]; do
    echo $IP
    ssh -n "kalm@$IP" "sudo k3s ctr -n k8s.io images tag docker.io/library/local-grader-matrix@sha256:14edea88b984f726fa0050aefbd4d404e9fb62e6f74ee994da9c23c5575f76bb docker.io/library/local-grader-matrix:latest"
done < ips.txt
