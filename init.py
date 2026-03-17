from glob_vars import *

import os
import subprocess
from git import Repo


###########################################
# GitHub Redirector Setup
###########################################
def create_directories():
    directories = ['files']
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            

def ensure_redirector_exists():
    if not os.path.exists(REDIRECTOR_PATH):
        git_log.info("Redirector repo not found. Cloning...")
        try:
            Repo.clone_from(REPO_URL, REDIRECTOR_PATH)
            git_log.info("Clone successful.")
        except Exception as e:
            git_log.error(f"Error cloning repo: {e}")
    else:
        git_log.info("Redirector repo already exists.")




#########################################################
def initialize():
    create_directories()
    ensure_redirector_exists()