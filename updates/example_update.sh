#!/bin/bash
source venv/bin/activate
git pull
pip install -r dependencies.txt
docker build -t lanhub-lab:latest -f tools/Dockerfile.lab .
