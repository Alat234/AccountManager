"""Process-wide, fail-fast ownership of AdsPower profiles.

Nested calls by the owning thread are allowed; unrelated operations are rejected.
External AdsPower clients/processes remain outside this local coordination boundary.
"""
from contextlib import contextmanager
from functools import wraps
import threading
from urllib.parse import urlsplit


class ProfileBusyError(RuntimeError):
    pass


class ProfileAccess:
    def __init__(self):
        self._lock = threading.Lock()
        self._owners = {}

    @contextmanager
    def hold(self, key):
        owner = threading.get_ident()
        with self._lock:
            current = self._owners.get(key)
            if current and current[0] != owner:
                raise ProfileBusyError('AdsPower profile is busy with another operation.')
            self._owners[key] = (owner, (current[1] if current else 0) + 1)
        try:
            yield
        finally:
            with self._lock:
                count = self._owners[key][1]
                if count == 1:
                    del self._owners[key]
                else:
                    self._owners[key] = (owner, count - 1)


PROFILE_ACCESS = ProfileAccess()


def profile_key(client, profile_id):
    url = getattr(client, 'base_url', '')
    endpoint = urlsplit(url if isinstance(url, str) else '')
    scope = 'local' if endpoint.hostname in (None, 'localhost', '127.0.0.1', 'local.adspower.net') else endpoint.netloc
    return scope, str(profile_id)


def guarded_profile(method):
    @wraps(method)
    def guarded(self, profile_id, *args, **kwargs):
        with PROFILE_ACCESS.hold(profile_key(self, profile_id)):
            return method(self, profile_id, *args, **kwargs)
    return guarded
