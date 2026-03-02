import re
import unittest
from pathlib import Path

from core.constants import VERSION


class TestVersionHistoryGuard(unittest.TestCase):
    def test_update_history_exists_and_mentions_current_version(self):
        history_path = Path("update_history.md")
        self.assertTrue(
            history_path.exists(),
            "버전 변경 시 update_history 동시 갱신 필요: update_history.md 파일이 없습니다.",
        )

        history = history_path.read_text(encoding="utf-8")
        version_section_pattern = rf"(?im)^##\s+v{re.escape(VERSION)}\b"
        self.assertRegex(
            history,
            version_section_pattern,
            "버전 변경 시 update_history 동시 갱신 필요: 현재 VERSION 섹션이 없습니다.",
        )

