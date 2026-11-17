"""retain_qthread_until_finished / retain_worker_until_finished 라이프사이클 테스트.

PROJECT_AUDIT.md 3.2: cleanup timeout 후 orphan thread가 _DETACHED_WORKERS에
등록되고 finished 시그널로 해제되는지, running이 아니면 즉시 해제되는지 검증.
"""

from __future__ import annotations

from core.workers_support import lifecycle


class _FakeSignal:
    """connect된 콜백을 저장하고 emit으로 호출하는 fake 시그널."""

    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def disconnect(self):
        self._slots.clear()

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class _FakeRunningThread:
    """retain_qthread_until_finished용 running 중인 fake thread."""

    def __init__(self, *, running=True):
        self._running = running
        self.finished = _FakeSignal()
        self.delete_later_calls = 0

    def isRunning(self):
        return self._running

    def deleteLater(self):
        self.delete_later_calls += 1


class _FakeWorkerWithSignals:
    """retain_worker_until_finished용 signal 기반 fake worker (QThread 아님)."""

    def __init__(self):
        self.finished = _FakeSignal()
        self.error = _FakeSignal()
        self.cancelled = _FakeSignal()
        self.settled = None
        self._running = True
        self.delete_later_calls = 0

    def isRunning(self):
        return self._running

    def deleteLater(self):
        self.delete_later_calls += 1


def _clear_detached():
    lifecycle._DETACHED_WORKERS.clear()


def test_retain_qthread_registers_running_thread():
    _clear_detached()
    thread = _FakeRunningThread(running=True)
    worker = _FakeRunningThread(running=True)
    try:
        lifecycle.retain_qthread_until_finished(thread, worker)
        assert id(thread) in lifecycle._DETACHED_WORKERS
        retained = lifecycle._DETACHED_WORKERS[id(thread)]
        assert thread in retained
        assert worker in retained
    finally:
        _clear_detached()


def test_retain_qthread_releases_on_finished_signal():
    _clear_detached()
    thread = _FakeRunningThread(running=True)
    worker = _FakeRunningThread(running=True)
    try:
        lifecycle.retain_qthread_until_finished(thread, worker)
        assert id(thread) in lifecycle._DETACHED_WORKERS

        thread.finished.emit()
        assert id(thread) not in lifecycle._DETACHED_WORKERS
        assert thread.delete_later_calls >= 1
        assert worker.delete_later_calls >= 1
    finally:
        _clear_detached()


def test_retain_qthread_releases_immediately_when_not_running():
    _clear_detached()
    thread = _FakeRunningThread(running=False)
    worker = _FakeRunningThread(running=False)
    try:
        lifecycle.retain_qthread_until_finished(thread, worker)
        assert id(thread) not in lifecycle._DETACHED_WORKERS
        assert thread.delete_later_calls >= 1
        assert worker.delete_later_calls >= 1
    finally:
        _clear_detached()


def test_retain_qthread_none_is_noop():
    _clear_detached()
    try:
        lifecycle.retain_qthread_until_finished(None)
        assert len(lifecycle._DETACHED_WORKERS) == 0
    finally:
        _clear_detached()


def test_retain_worker_with_signals_registers_and_releases_on_finished():
    _clear_detached()
    worker = _FakeWorkerWithSignals()
    try:
        lifecycle.retain_worker_until_finished(worker)
        assert id(worker) in lifecycle._DETACHED_WORKERS

        worker.finished.emit()
        assert id(worker) not in lifecycle._DETACHED_WORKERS
        assert worker.delete_later_calls >= 1
    finally:
        _clear_detached()


def test_retain_worker_releases_on_error_signal():
    _clear_detached()
    worker = _FakeWorkerWithSignals()
    try:
        lifecycle.retain_worker_until_finished(worker)
        assert id(worker) in lifecycle._DETACHED_WORKERS

        worker.error.emit("boom")
        assert id(worker) not in lifecycle._DETACHED_WORKERS
    finally:
        _clear_detached()


def test_retain_worker_releases_on_cancelled_signal():
    _clear_detached()
    worker = _FakeWorkerWithSignals()
    try:
        lifecycle.retain_worker_until_finished(worker)
        assert id(worker) in lifecycle._DETACHED_WORKERS

        worker.cancelled.emit()
        assert id(worker) not in lifecycle._DETACHED_WORKERS
    finally:
        _clear_detached()


def test_retain_worker_none_is_noop():
    _clear_detached()
    try:
        lifecycle.retain_worker_until_finished(None)
        assert len(lifecycle._DETACHED_WORKERS) == 0
    finally:
        _clear_detached()
