#!/bin/bash
#! git pull is already ran in backend
source venv/bin/activate
pip install -r dependencies.txt
docker build -t lanhub-lab:latest -f tools/Dockerfile.lab .

#! test sudo access
sudo -v

sudo apt-get update