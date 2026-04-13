# pyright: reportMissingModuleSource=false
import unittest
from typing import Any, cast

import requests

from ui._settings_dialog_tasks import _SettingsDialogTasksMixin


class _DummySpinBox:
    def __init__(self, value: int):
        self._value = value

    def value(self) -> int:
        return self._value


class _DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return dict(self._payload)


class _DummySession:
    def __init__(self, response: _DummyResponse | None = None, *, raises: BaseException | None = None):
        self.response = response or _DummyResponse(200)
        self.raises = raises
        self.calls: list[dict[str, Any]] = []
        self.close_called = False

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.raises is not None:
            raise self.raises
        return self.response

    def close(self):
        self.close_called = True


class _DummyParent:
    def __init__(self, session: _DummySession):
        self.session = session
        self.create_http_session_calls = 0

    def create_http_session(self):
        self.create_http_session_calls += 1
        return self.session


class _ValidationDialog:
    def __init__(self, parent=None, timeout: int = 15):
        self._parent = parent
        self.spn_api_timeout = _DummySpinBox(timeout)

    def _typed_parent(self):
        return self._parent

    def _current_api_timeout(self):
        return cast(Any, _SettingsDialogTasksMixin)._current_api_timeout(cast(Any, self))

    def _create_validation_session(self):
        return cast(Any, _SettingsDialogTasksMixin)._create_validation_session(cast(Any, self))

    def _run_api_validation_request(self, client_id: str, client_secret: str, *, timeout: int):
        return cast(Any, _SettingsDialogTasksMixin)._run_api_validation_request(
            cast(Any, self),
            client_id,
            client_secret,
            timeout=timeout,
        )


class TestSettingsValidationHttpPolicy(unittest.TestCase):
    def test_validation_uses_parent_session_and_current_timeout(self):
        session = _DummySession(response=_DummyResponse(200))
        parent = _DummyParent(session)
        dialog = _ValidationDialog(parent=parent, timeout=27)

        result = dialog._run_api_validation_request(
            "id",
            "secret",
            timeout=dialog._current_api_timeout(),
        )

        self.assertEqual(parent.create_http_session_calls, 1)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0]["timeout"], 27)
        self.assertTrue(session.close_called)
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["error_kind"], "")

    def test_validation_timeout_returns_timeout_kind_and_closes_session(self):
        session = _DummySession(raises=requests.Timeout("slow"))
        parent = _DummyParent(session)
        dialog = _ValidationDialog(parent=parent, timeout=33)

        result = dialog._run_api_validation_request(
            "id",
            "secret",
            timeout=dialog._current_api_timeout(),
        )

        self.assertEqual(result["status_code"], 0)
        self.assertEqual(result["error_kind"], "timeout")
        self.assertIn("33초", result["error_message"])
        self.assertTrue(session.close_called)


if __name__ == "__main__":
    unittest.main()
