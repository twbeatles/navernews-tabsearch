import importlib
import unittest

import pytest

# The root wrapper re-exports the whole application surface, so importing it
# pulls in every optional runtime dependency. Skip rather than fail when one is
# unavailable, matching the collection-time behaviour in conftest.py.
pytest.importorskip("PyQt6")
pytest.importorskip("cryptography")


class TestEntrypointBootstrap(unittest.TestCase):
    def test_news_scraper_main_is_bootstrap_main(self):
        app = importlib.import_module('news_scraper_pro')
        bootstrap = importlib.import_module('core.bootstrap')
        self.assertIs(app.main, bootstrap.main)


if __name__ == '__main__':
    unittest.main()
