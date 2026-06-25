# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
import unittest
from typing import Any, cast

from ui.main_window_io_support.cloud import _MainWindowCloudSyncMixin


class _DummyCloudMain(_MainWindowCloudSyncMixin):
    def __init__(self, *, refresh_in_progress: bool = False, sequential_refresh: bool = False):
        self.cloud_sync_enabled = True
        self.cloud_sync_dir = r"C:\sync"
        self._refresh_in_progress = refresh_in_progress
        self._sequential_refresh_active = sequential_refresh
        self._cloud_sync_worker = None
        self._maintenance_mode = False
        self.runtime_paths = cast(Any, object())

    def is_maintenance_mode_active(self):
        return bool(self._maintenance_mode)


class TestCloudSyncBlocksDuringRefresh(unittest.TestCase):
    def test_block_reason_when_refresh_in_progress(self):
        main = _DummyCloudMain(refresh_in_progress=True)
        with unittest.mock.patch(
            "ui.main_window_io_support.cloud.runtime_storage_is_probably_cloud",
            return_value=False,
        ):
            with unittest.mock.patch(
                "ui.main_window_io_support.cloud.cloud_sync_path_conflicts_with_runtime",
                return_value=False,
            ):
                reason = main._cloud_sync_block_reason()
        self.assertIn("새로고침", reason)

    def test_block_reason_when_sequential_refresh_active(self):
        main = _DummyCloudMain(sequential_refresh=True)
        with unittest.mock.patch(
            "ui.main_window_io_support.cloud.runtime_storage_is_probably_cloud",
            return_value=False,
        ):
            with unittest.mock.patch(
                "ui.main_window_io_support.cloud.cloud_sync_path_conflicts_with_runtime",
                return_value=False,
            ):
                reason = main._cloud_sync_block_reason()
        self.assertIn("새로고침", reason)


if __name__ == "__main__":
    unittest.main()