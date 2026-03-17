import unittest
from pathlib import Path


class TestSpecRuntimeTmpdir(unittest.TestCase):
    def test_spec_does_not_embed_user_specific_runtime_tmpdir(self):
        src = Path("news_scraper_pro.spec").read_text(encoding="utf-8")
        self.assertIn("runtime_tmpdir=None", src)
        self.assertNotIn("LOCALAPPDATA", src)
        self.assertNotIn("os.environ.get('TEMP'", src)

