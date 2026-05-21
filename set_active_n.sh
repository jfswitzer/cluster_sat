#!/bin/bash
IN=$1
echo $IN
kubectl get nodes -l usage=subset --no-headers | awk '{print $1}' | xargs -I {} kubectl label node {} usage-
kubectl get nodes --no-headers | head -n $IN | awk '{print $1}' | xargs -I {} kubectl label node {} usage=subset
