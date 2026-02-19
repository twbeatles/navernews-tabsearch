from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class WorkerHandle:
    request_id: int
    tab_keyword: str
    search_keyword: str
    exclude_words: List[str]
    worker: object
    thread: object


class WorkerRegistry:
    def __init__(self):
        self._handles_by_request_id: Dict[int, WorkerHandle] = {}
        self._active_request_id_by_tab_keyword: Dict[str, int] = {}

    def register(self, handle: WorkerHandle) -> None:
        self._handles_by_request_id[handle.request_id] = handle
        self._active_request_id_by_tab_keyword[handle.tab_keyword] = handle.request_id

    def get_by_request_id(self, request_id: int) -> Optional[WorkerHandle]:
        return self._handles_by_request_id.get(request_id)

    def get_active_request_id(self, tab_keyword: str) -> Optional[int]:
        return self._active_request_id_by_tab_keyword.get(tab_keyword)

    def get_active_handle(self, tab_keyword: str) -> Optional[WorkerHandle]:
        request_id = self.get_active_request_id(tab_keyword)
        if request_id is None:
            return None
        return self.get_by_request_id(request_id)

    def is_active(self, tab_keyword: str, request_id: int) -> bool:
        return self._active_request_id_by_tab_keyword.get(tab_keyword) == request_id

    def pop_by_request_id(self, request_id: int) -> Optional[WorkerHandle]:
        handle = self._handles_by_request_id.pop(request_id, None)
        if not handle:
            return None
        active_request_id = self._active_request_id_by_tab_keyword.get(handle.tab_keyword)
        if active_request_id == request_id:
            self._active_request_id_by_tab_keyword.pop(handle.tab_keyword, None)
        return handle

    def clear_active_if_matches(self, tab_keyword: str, request_id: int) -> None:
        if self._active_request_id_by_tab_keyword.get(tab_keyword) == request_id:
            self._active_request_id_by_tab_keyword.pop(tab_keyword, None)

    def all_handles(self) -> List[WorkerHandle]:
        return list(self._handles_by_request_id.values())
