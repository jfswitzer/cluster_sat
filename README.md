# cluster_sat

## Helper scripts

1. *set_active_n.sh* sets the number of nodes that are active and will be deployed to

2. *enable_nopasswd.sh* allow kalm user to use passwordless sudo on all devices (should already be set up)

## Running
1. Run workload_generator.py
   a. takes number of concurrent jobs to target
2. capacity_sweep.sh tries to sweep through different targets for capacity
3. node_size_sweep.sh changes number of nodes that are active
