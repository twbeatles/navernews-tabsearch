from __future__ import annotations

from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter


@dataclass(frozen=True)
class HttpClientConfig:
    pool_connections: int = 20
    pool_maxsize: int = 20
    max_retries: int = 0
    user_agent: str = "NewsScraperPro/32.7.3"

    def create_session(self) -> requests.Session:
        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=max(1, int(self.pool_connections)),
            pool_maxsize=max(1, int(self.pool_maxsize)),
            max_retries=max(0, int(self.max_retries)),
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({"User-Agent": self.user_agent})
        return session
