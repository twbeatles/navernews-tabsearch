"""Text-mode file IO must declare an explicit encoding.

Windows CI runs with a legacy default locale encoding (cp1252), while local
Linux checkouts default to UTF-8. A ``Path.read_text()`` without ``encoding``
passes locally and then fails on CI once the file holds non-ASCII text (for
example the Korean messages in update result JSON). This guard scans the
application sources with ``ast`` so such calls fail locally before CI.
"""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("core", "ui", "scripts", "tests")
SCAN_ROOT_FILES = tuple(ROOT.glob("*.py")) + (ROOT / "news_scraper_pro.py",)
_SEEN: set[Path] = set()


def _iter_target_files():
    targets: list[Path] = []
    for name in SCAN_DIRS:
        targets.extend(sorted((ROOT / name).rglob("*.py")))
    for path in SCAN_ROOT_FILES:
        if path.is_file():
            targets.append(path)
    for path in targets:
        if path not in _SEEN:
            _SEEN.add(path)
            yield path


def _mode_arg(node: ast.Call, mode_index: int) -> ast.expr | None:
    for keyword in node.keywords:
        if keyword.arg == "mode":
            return keyword.value
    if len(node.args) > mode_index:
        return node.args[mode_index]
    return None


def _is_binary_mode(mode: ast.expr | None) -> bool:
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return "b" in mode.value
    # Non-literal mode: cannot prove binary, treat as text.
    return False


def _has_encoding(node: ast.Call) -> bool:
    return any(keyword.arg == "encoding" for keyword in node.keywords)


def _check_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [f"{path}:{exc}"]
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"read_text", "write_text"}:
            if not _has_encoding(node):
                violations.append(f"{path}:{node.lineno}: .{func.attr}() without encoding=")
        elif isinstance(func, ast.Name) and func.id in {"open", "fdopen"}:
            mode = _mode_arg(node, 1)
            if not _is_binary_mode(mode) and not _has_encoding(node):
                violations.append(f"{path}:{node.lineno}: {func.id}() text mode without encoding=")
        elif isinstance(func, ast.Attribute) and func.attr == "fdopen":
            mode = _mode_arg(node, 1)
            if not _is_binary_mode(mode) and not _has_encoding(node):
                violations.append(f"{path}:{node.lineno}: fdopen() text mode without encoding=")
        elif isinstance(func, ast.Attribute) and func.attr == "open":
            # Path.open(mode) vs ZipFile.open(name): only judge calls whose
            # first positional argument is a mode string literal, plus bare
            # no-arg opens (Path.open() defaults to text "r"). Anything else
            # (e.g. zf.open(member)) is left to review.
            if not node.args and not any(k.arg == "mode" for k in node.keywords):
                if not _has_encoding(node):
                    violations.append(f"{path}:{node.lineno}: .open() without mode/encoding=")
            elif node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                if not _is_binary_mode(node.args[0]) and not _has_encoding(node):
                    violations.append(f"{path}:{node.lineno}: .open() text mode without encoding=")
    return violations


class TestTextIoEncoding(unittest.TestCase):
    def test_text_mode_io_declares_encoding(self):
        violations: list[str] = []
        for path in _iter_target_files():
            violations.extend(_check_file(path))
        self.assertEqual(
            violations,
            [],
            msg="Explicit encoding= required (Windows CI defaults to cp1252):\n" + "\n".join(violations),
        )
