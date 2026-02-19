import os
import sys


def get_app_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


APP_DIR = get_app_dir()
LOG_FILE = os.path.join(APP_DIR, 'news_scraper.log')
CONFIG_FILE = os.path.join(APP_DIR, 'news_scraper_config.json')
DB_FILE = os.path.join(APP_DIR, 'news_database.db')
ICON_FILE = 'news_icon.ico'
ICON_PNG = 'news_icon.png'
APP_NAME = '\ub274\uc2a4 \uc2a4\ud06c\ub798\ud37c Pro'
VERSION = '32.7.1'
PENDING_RESTORE_FILENAME = 'pending_restore.json'
PENDING_RESTORE_FILE = os.path.join(APP_DIR, PENDING_RESTORE_FILENAME)
