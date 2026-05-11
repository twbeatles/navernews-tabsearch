from ui.main_window_fetch_support.refresh_flow import _MainWindowRefreshFlowMixin
from ui.main_window_fetch_support.worker_flow import _MainWindowFetchWorkerMixin


class _MainWindowFetchMixin(_MainWindowRefreshFlowMixin, _MainWindowFetchWorkerMixin):
    """Composes refresh policy and worker lifecycle behavior for MainApp."""


__all__ = ["_MainWindowFetchMixin"]
