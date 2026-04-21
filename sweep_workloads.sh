#!/bin/bash

datestring=$(date +"%Y-%m-%d_%H-%M-%S")
for i in 5 15 25 35 45 55 75 85; do
    python3 workload_w_metrics.py $1 &> $1_$datestring.out 
done
