from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any, Callable, Hashable


@dataclass(slots=True)
class _CacheEntry:
    value: Any
    created_at: float
    database_mtime_ns: int


class AnalyticsCache:
    """Thread-safe in-memory cache that invalidates when the DuckDB file changes."""

    _shared: dict[str, "AnalyticsCache"] = {}
    _shared_lock = RLock()

    def __init__(
        self,
        database_path: str,
        ttl_seconds: float = 300.0,
        max_entries: int = 256,
    ) -> None:
        self.database_path = str(Path(database_path))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._entries: dict[Hashable, _CacheEntry] = {}
        self._lock = RLock()

    @classmethod
    def shared(
        cls,
        database_path: str,
        ttl_seconds: float = 300.0,
        max_entries: int = 256,
    ) -> "AnalyticsCache":
        key = str(Path(database_path).resolve())
        with cls._shared_lock:
            cache = cls._shared.get(key)
            if cache is None:
                cache = cls(key, ttl_seconds, max_entries)
                cls._shared[key] = cache
            return cache

    def _database_mtime_ns(self) -> int:
        try:
            return Path(self.database_path).stat().st_mtime_ns
        except OSError:
            return 0

    @staticmethod
    def make_key(namespace: str, **filters: Any) -> tuple[Any, ...]:
        normalized = tuple(
            sorted(
                (str(key), AnalyticsCache._freeze(value))
                for key, value in filters.items()
            )
        )
        return str(namespace), normalized

    @staticmethod
    def _freeze(value: Any) -> Hashable:
        if isinstance(value, dict):
            return tuple(sorted((str(k), AnalyticsCache._freeze(v)) for k, v in value.items()))
        if isinstance(value, (list, tuple, set, frozenset)):
            return tuple(AnalyticsCache._freeze(item) for item in value)
        try:
            hash(value)
            return value
        except TypeError:
            return repr(value)

    def get(self, key: Hashable) -> Any | None:
        now = monotonic()
        current_mtime = self._database_mtime_ns()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expired = self.ttl_seconds > 0 and now - entry.created_at > self.ttl_seconds
            database_changed = entry.database_mtime_ns != current_mtime
            if expired or database_changed:
                self._entries.pop(key, None)
                return None
            return deepcopy(entry.value)

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            if len(self._entries) >= self.max_entries:
                oldest_key = min(
                    self._entries,
                    key=lambda item: self._entries[item].created_at,
                )
                self._entries.pop(oldest_key, None)
            self._entries[key] = _CacheEntry(
                value=deepcopy(value),
                created_at=monotonic(),
                database_mtime_ns=self._database_mtime_ns(),
            )

    def get_or_compute(self, key: Hashable, factory: Callable[[], Any]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value)
        return deepcopy(value)

    def invalidate(self, namespace: str | None = None) -> None:
        with self._lock:
            if namespace is None:
                self._entries.clear()
                return
            prefix = str(namespace)
            for key in list(self._entries):
                if isinstance(key, tuple) and key and str(key[0]) == prefix:
                    self._entries.pop(key, None)
