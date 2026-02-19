import importlib
import unittest


class TestEntrypointBootstrap(unittest.TestCase):
    def test_news_scraper_main_is_bootstrap_main(self):
        app = importlib.import_module('news_scraper_pro')
        bootstrap = importlib.import_module('core.bootstrap')
        self.assertIs(app.main, bootstrap.main)


if __name__ == '__main__':
    unittest.main()
