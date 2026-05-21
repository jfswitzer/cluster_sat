#!/bin/bash

./set_active_n.sh 10
./capacity_sweep.sh | tee 10node_sweep.txt

./set_active_n.sh 15
./capacity_sweep.sh | tee 15node_sweep.txt
