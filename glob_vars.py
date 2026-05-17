# glob_vars.py
from config import *
import os
import logging
from logging.handlers import RotatingFileHandler


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


###########################################################
# Database Vars
###########################################################
DB_PATH = os.path.join(BASE_DIR, "app.db")


###########################################################
# Logging Vars
###########################################################
LOG_DIR = "logs"
LOG_MAXBYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUPCOUNT = 3

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def setup_logger(name, log_file, level=logging.INFO):
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, log_file),
        maxBytes=LOG_MAXBYTES,
        backupCount=LOG_BACKUPCOUNT
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger

access_log = setup_logger('access', 'access.log')
app_log    = setup_logger('app',    'app.log')
git_log    = setup_logger('github', 'github_sync.log')
error_log  = setup_logger('error',  'error.log', level=logging.ERROR)