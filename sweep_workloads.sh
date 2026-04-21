#!/bin/bash

capacities=(5 15 25 35 45 55 65 75)
datestring=$(date +"%Y-%m-%d_%H-%M-%S")
for i in "${capacities[@]}"; do
    echo $i
    python3 workload_w_metrics.py $i &> $i_$datestring.out 
done
