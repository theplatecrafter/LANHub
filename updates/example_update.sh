#!/bin/bash
#! git pull is already ran in backend
source venv/bin/activate
pip install -r dependencies.txt
docker build -t lanhub-lab:latest -f tools/Dockerfile.lab .

#! test sudo access
sudo -n true || { echo "This script requires sudo access. Please run with sudo." >&2; exit 1; }
