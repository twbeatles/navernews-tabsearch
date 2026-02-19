import tempfile
import unittest
from pathlib import Path

from core.backup_guard import run_pre_refactor_backup, verify_backup


class TestRefactorBackupGuard(unittest.TestCase):
    def test_backup_generates_manifest_and_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'src'
            dst_parent = Path(td) / 'out'
            src.mkdir(parents=True, exist_ok=True)
            (src / 'a.txt').write_text('hello', encoding='utf-8')
            (src / 'b.bin').write_bytes(b'abc123')

            backup_path = Path(run_pre_refactor_backup(str(src), str(dst_parent), prefix='test_backup_'))
            self.assertTrue(backup_path.exists())
            self.assertTrue((backup_path / 'backup_manifest.txt').exists())
            self.assertTrue((backup_path / 'backup_hashes.sha256').exists())

    def test_verify_backup_detects_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'src'
            dst = Path(td) / 'dst'
            src.mkdir(parents=True, exist_ok=True)
            dst.mkdir(parents=True, exist_ok=True)
            (src / 'a.txt').write_text('x', encoding='utf-8')
            (dst / 'a.txt').write_text('x', encoding='utf-8')
            self.assertTrue(verify_backup(str(src), str(dst)))

            (dst / 'b.txt').write_text('extra', encoding='utf-8')
            self.assertFalse(verify_backup(str(src), str(dst)))


if __name__ == '__main__':
    unittest.main()
