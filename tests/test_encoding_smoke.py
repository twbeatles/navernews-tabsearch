import unittest
from pathlib import Path
import re


class TestEncodingSmoke(unittest.TestCase):
    _KNOWN_BROKEN_TOKEN = "\u003f\u317b\uca9f"
    _TEXT_SUFFIXES = {
        ".py",
        ".md",
        ".txt",
        ".json",
        ".ini",
        ".cfg",
        ".spec",
        ".yml",
        ".yaml",
    }
    _SKIP_DIRS = {".git", "build", "dist", "__pycache__", ".pytest_cache"}
    _BROKEN_TOKENS = {
        _KNOWN_BROKEN_TOKEN,
        "\u907a\uacf7\ucb4f",
        "\u5a9b\x80?\uba84\uc0a9",
        "\u8b70\uace0\uc276",
        "\u8adb\uae46",
        "\u4ee5\ubb10\ub0ac",
        "?\uafaa\uaf63",
        "?\ub348\uc908",
        "?\uc88e\ucb68",
        "?\u0448\ud00e",
        "\u5bc3\x80\uf9dd",
    }
    _BROKEN_PATTERNS = (
        re.compile(r"\?[가-힣]{2,}"),
        re.compile(r"[가-힣][一-龥]|[一-龥][가-힣]"),
        re.compile(r"[가-힣][Ѐ-ӿ]|[Ѐ-ӿ][가-힣]"),
        re.compile(r"[가-힣][À-ÿ]|[À-ÿ][가-힣]"),
    )

    def _iter_repo_text_files(self):
        for path in Path(".").rglob("*"):
            if not path.is_file():
                continue
            if any(part in self._SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in self._TEXT_SUFFIXES:
                yield path

    def test_known_broken_token_removed_from_news_tab(self):
        src = Path("ui/news_tab.py").read_text(encoding="utf-8")
        self.assertNotIn(self._KNOWN_BROKEN_TOKEN, src)

    def test_repo_text_assets_are_valid_utf8_without_replacement_chars(self):
        bad_files = []
        broken_token_files = []
        broken_pattern_files = []

        for path in self._iter_repo_text_files():
            try:
                src = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                bad_files.append(f"{path}: {exc}")
                continue

            if "\ufffd" in src:
                bad_files.append(str(path))
            if any(token in src for token in self._BROKEN_TOKENS):
                broken_token_files.append(str(path))
            for pattern in self._BROKEN_PATTERNS:
                match = pattern.search(src)
                if match is not None:
                    broken_pattern_files.append(f"{path}: {match.group(0)}")
                    break

        self.assertEqual(
            bad_files,
            [],
            msg=f"UTF-8 decode or replacement-character issue found in: {', '.join(bad_files)}",
        )
        self.assertEqual(
            broken_token_files,
            [],
            msg=f"Known broken token found in: {', '.join(broken_token_files)}",
        )
        self.assertEqual(
            broken_pattern_files,
            [],
            msg=f"Suspicious mojibake pattern found in: {', '.join(broken_pattern_files)}",
        )

