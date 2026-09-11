"""Route worker scheduling to Tk's owning thread."""
import queue
import threading
import logging


class ThreadDispatchMixin:
    def init_dispatch(self):
        self._ui_owner = threading.get_ident()
        self._ui_calls = queue.SimpleQueue()
        self._ui_dispatch_closed = False
        super().after(50, self._drain_ui_calls)

    def after(self, ms, func=None, *args):
        if hasattr(self, '_ui_owner') and threading.get_ident() != self._ui_owner:
            if func is not None and not self._ui_dispatch_closed:
                self._ui_calls.put((ms, func, args))
            return None
        return super().after(ms, func, *args)

    def _drain_ui_calls(self):
        if self._ui_dispatch_closed:
            return
        for _ in range(100):
            try:
                ms, func, args = self._ui_calls.get_nowait()
            except queue.Empty:
                break
            try:
                super().after(ms, func, *args)
            except Exception:
                logging.getLogger(__name__).exception('UI scheduling failed')
        super().after(50, self._drain_ui_calls)

    def destroy(self):
        self._ui_dispatch_closed = True
        return super().destroy()
