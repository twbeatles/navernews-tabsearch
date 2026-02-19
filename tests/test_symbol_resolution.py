import builtins
import symtable
import unittest
from pathlib import Path


class TestSymbolResolution(unittest.TestCase):
    def _collect_defs(self, table: symtable.SymbolTable) -> set[str]:
        names: set[str] = set()
        for symbol in table.get_symbols():
            if (
                symbol.is_imported()
                or symbol.is_assigned()
                or symbol.is_parameter()
                or symbol.is_namespace()
            ):
                names.add(symbol.get_name())
        return names

    def _find_unresolved(self, path: Path) -> set[str]:
        source = path.read_text(encoding="utf-8")
        module_table = symtable.symtable(source, str(path), "exec")
        builtin_names = set(dir(builtins))
        unresolved: set[str] = set()

        def walk(table: symtable.SymbolTable, accessible_defs: set[str]) -> None:
            local_defs = self._collect_defs(table)
            for symbol in table.get_symbols():
                name = symbol.get_name()
                if not symbol.is_referenced():
                    continue
                if symbol.is_free():
                    continue
                if name.startswith("__"):
                    continue
                if name in local_defs or name in accessible_defs or name in builtin_names:
                    continue
                unresolved.add(name)

            for child in table.get_children():
                walk(child, accessible_defs | local_defs)

        walk(module_table, self._collect_defs(module_table))
        return unresolved

    def test_ui_and_startup_modules_have_no_unresolved_symbols(self):
        targets = [
            Path("ui/main_window.py"),
            Path("ui/settings_dialog.py"),
            Path("ui/news_tab.py"),
            Path("core/startup.py"),
        ]
        for path in targets:
            unresolved = self._find_unresolved(path)
            self.assertEqual(unresolved, set(), f"{path} unresolved: {sorted(unresolved)}")

