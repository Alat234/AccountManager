"""Cooperative operation control; never calls Tk or WebDriver from UI threads."""
import threading
import time
from contextlib import contextmanager


class OperationCancelled(RuntimeError):
    pass


class OperationControl:
    def __init__(self):
        self.cancelled = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._lock = threading.Lock()
        self._state = 'queued'
        self._heartbeat = time.monotonic()
        self._resuming = False
        self._atomic_depth = 0

    @contextmanager
    def atomic(self):
        """Defer pause across a short code-generation/submit sequence; cancellation still works."""
        self.check()
        with self._lock:
            self._atomic_depth += 1
        try:
            yield
        finally:
            with self._lock:
                self._atomic_depth -= 1

    def snapshot(self):
        with self._lock:
            return {'state': self._state, 'heartbeat_age': time.monotonic() - self._heartbeat}

    def pause(self):
        with self._lock:
            if not self.cancelled.is_set():
                self._state = 'pause_requested'
                self._resume.clear()

    def resume(self):
        with self._lock:
            if not self.cancelled.is_set():
                self._resuming = True
                self._state = 'running'
                self._resume.set()

    def cancel(self):
        with self._lock:
            self._state = 'cancelling'
            self.cancelled.set()
            self._resume.set()

    def check(self):
        while True:
            if self.cancelled.is_set():
                raise OperationCancelled('Операцію припинено користувачем')
            with self._lock:
                self._heartbeat = time.monotonic()
                ready = self._resume.is_set() or self._atomic_depth > 0
                self._state = ('pause_requested' if ready and not self._resume.is_set() else
                               'running' if ready else 'paused')
            if ready:
                return
            self._resume.wait(0.2)

    def take_resumed(self):
        with self._lock:
            result = self._resuming
            self._resuming = False
            return result

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while True:
            self.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self.cancelled.wait(min(remaining, 0.2))
