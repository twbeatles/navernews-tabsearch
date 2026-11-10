"""_check_integrity 의 예외 처리 일관성 테스트.

PROJECT_AUDIT.md 3.4: except (sqlite3.Error, OSError) 를 except Exception 으로
넓혀, sqlite3/OSError 외의 예상치 못한 예외도 unreadable 로 처리되는지 검증.
기존에는 RuntimeError 등이 전파되어 finally 는 동작하나 unreadable 상태로
분류되지 않았다.
"""
from __future__ import annotations

import sqlite3
import unittest
from typing import Any, cast
from unittest import mock

from core._db_schema import _DatabaseSchemaMixin


class _SchemaHarness(_DatabaseSchemaMixin):
    def __init__(self, db_file: str):
        self.db_file = db_file


class TestCheckIntegrityUnexpectedException(unittest.TestCase):
    def test_runtime_error_treated_as_unreadable(self):
        harness = _SchemaHarness("dummy.db")
        with mock.patch(
            "core._db_schema.sqlite3.connect",
            side_effect=RuntimeError("unexpected internal error"),
        ):
            result = cast(Any, harness)._check_integrity()
        self.assertEqual(result.state, "unreadable")
        self.assertIn("unexpected internal error", result.detail)

    def test_value_error_treated_as_unreadable(self):
        harness = _SchemaHarness("dummy.db")
        with mock.patch(
            "core._db_schema.sqlite3.connect",
            side_effect=ValueError("bad value"),
        ):
            result = cast(Any, harness)._check_integrity()
        self.assertEqual(result.state, "unreadable")
        self.assertIn("bad value", result.detail)

    def test_sqlite_error_still_treated_as_unreadable(self):
        """기존 동작 회귀 방지: sqlite3.Error 는 여전히 unreadable."""
        harness = _SchemaHarness("dummy.db")
        with mock.patch(
            "core._db_schema.sqlite3.connect",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            result = cast(Any, harness)._check_integrity()
        self.assertEqual(result.state, "unreadable")
        self.assertIn("locked", result.detail)
