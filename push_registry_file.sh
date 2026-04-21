#!/bin/bash

while IFS= read -r line || [[ -n "$line" ]]; do
    # Replace 'echo' with your desired command
    scp registries.yaml kalm@$line:/home/kalm 
    scp setup_registry.sh kalm@$line:/home/kalm
done < "ips.txt"
