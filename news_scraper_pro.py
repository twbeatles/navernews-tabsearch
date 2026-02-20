import os

os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')

from core.constants import (
    APP_DIR,
    APP_NAME,
    CONFIG_FILE,
    DB_FILE,
    ICON_FILE,
    ICON_PNG,
    LOG_FILE,
    VERSION,
)
from core.config_store import default_config, load_config_file, save_config_file_atomic
from core.database import DatabaseManager
from core.keyword_groups import KeywordGroupManager
from core.notifications import NotificationSound
from core.query_parser import build_fetch_key, has_positive_keyword, parse_tab_query
from core.startup import StartupManager
from core.text_utils import (
    RE_BOLD_TAGS,
    RE_HTML_TAGS,
    RE_WHITESPACE,
    TextUtils,
    get_highlight_pattern,
    parse_date_string,
    parse_date_to_ts,
    perf_timer,
)
from core.validation import ValidationUtils
from core.worker_registry import WorkerHandle, WorkerRegistry
from core.workers import ApiWorker, AsyncJobWorker, DBWorker
from ui.dialogs import BackupDialog, KeywordGroupDialog, LogViewerDialog, NoteDialog
from ui.main_window import (
    AutoBackup,
    MainApp,
    PENDING_RESTORE_FILE,
    PENDING_RESTORE_FILENAME,
    apply_pending_restore_if_any,
)
from ui.news_tab import NewsTab
from ui.settings_dialog import SettingsDialog
from ui.styles import AppStyle, Colors, ToastType, UIConstants
from ui.toast import ToastMessage, ToastQueue
from ui.widgets import NewsBrowser, NoScrollComboBox
from core.bootstrap import main

__all__ = [
    'APP_DIR',
    'APP_NAME',
    'CONFIG_FILE',
    'DB_FILE',
    'ICON_FILE',
    'ICON_PNG',
    'LOG_FILE',
    'VERSION',
    'PENDING_RESTORE_FILENAME',
    'PENDING_RESTORE_FILE',
    'default_config',
    'load_config_file',
    'save_config_file_atomic',
    'parse_tab_query',
    'has_positive_keyword',
    'build_fetch_key',
    'DatabaseManager',
    'AutoBackup',
    'apply_pending_restore_if_any',
    'WorkerHandle',
    'WorkerRegistry',
    'AsyncJobWorker',
    'ApiWorker',
    'DBWorker',
    'ValidationUtils',
    'TextUtils',
    'StartupManager',
    'NotificationSound',
    'KeywordGroupManager',
    'ToastQueue',
    'ToastMessage',
    'NoScrollComboBox',
    'NewsBrowser',
    'NoteDialog',
    'LogViewerDialog',
    'BackupDialog',
    'KeywordGroupDialog',
    'NewsTab',
    'MainApp',
    'SettingsDialog',
    'Colors',
    'UIConstants',
    'ToastType',
    'AppStyle',
    'RE_HTML_TAGS',
    'RE_WHITESPACE',
    'RE_BOLD_TAGS',
    'perf_timer',
    'parse_date_string',
    'parse_date_to_ts',
    'get_highlight_pattern',
    'main',
]


if __name__ == '__main__':
    main()
