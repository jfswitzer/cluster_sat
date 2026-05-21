#!/bin/bash

#capacities=(10 20 40 50 60 70 80 90 100 110 120)
capacities=(5 20 60)
datestring=$(date +"%Y-%m-%d_%H-%M-%S")
for i in "${capacities[@]}"; do
    echo $i
    python3 workload_generator.py $i
done
