#!/bin/bash
sudo mv /home/kalm/registries.yaml /etc/rancher/k3s/registries.yaml
if systemctl is-active --quiet k3s; then
    sudo systemctl restart k3s
else
    sudo systemctl restart k3s-agent
fi
