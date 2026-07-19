from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any


class GTOReferenceService:
    """Persistent user-entered GTO frequencies with an in-memory cache."""

    def __init__(self, path: str = "database/gto_board_references.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._cache: dict[str, float] | None = None
        self._cache_mtime_ns: int | None = None

    @staticmethod
    def _key(
        site: str,
        stakes: str,
        board_family: str,
        street: str,
        metric: str,
    ) -> str:
        return "|".join([
            (site or "ALL").strip(),
            (stakes or "ALL").strip(),
            (board_family or "ALL").strip(),
            (street or "ALL").strip().upper(),
            (metric or "ALL").strip().upper(),
        ])

    def _current_mtime(self) -> int | None:
        try:
            return self.path.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def _load(self, force: bool = False) -> dict[str, float]:
        with self._lock:
            current_mtime = self._current_mtime()
            if (
                not force
                and self._cache is not None
                and current_mtime == self._cache_mtime_ns
            ):
                return self._cache

            data: dict[str, float] = {}
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        for key, value in raw.items():
                            if value is None:
                                continue
                            try:
                                data[str(key)] = float(value)
                            except (TypeError, ValueError):
                                continue
                except (OSError, json.JSONDecodeError):
                    data = {}

            self._cache = data
            self._cache_mtime_ns = current_mtime
            return self._cache

    def get(
        self,
        site: str,
        stakes: str,
        board_family: str,
        street: str,
        metric: str,
    ) -> float | None:
        data = self._load()
        candidates = [
            self._key(site, stakes, board_family, street, metric),
            self._key(site, "", board_family, street, metric),
            self._key("", "", board_family, street, metric),
            self._key("", "", "", street, metric),
        ]
        for key in candidates:
            if key in data:
                return float(data[key])
        return None

    def get_many(
        self,
        requests: list[tuple[str, str, str, str, str]],
    ) -> list[float | None]:
        return [self.get(*request) for request in requests]

    def set(
        self,
        site: str,
        stakes: str,
        board_family: str,
        street: str,
        metric: str,
        value: float | None,
    ) -> None:
        with self._lock:
            data = dict(self._load())
            key = self._key(site, stakes, board_family, street, metric)

            if value is None:
                data.pop(key, None)
            else:
                data[key] = max(0.0, min(100.0, float(value)))

            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            temp.replace(self.path)

            self._cache = data
            self._cache_mtime_ns = self._current_mtime()

    def clear(self) -> None:
        with self._lock:
            if self.path.exists():
                self.path.unlink()
            self._cache = {}
            self._cache_mtime_ns = None

    def export_all(self) -> dict[str, float]:
        return dict(self._load())

    @staticmethod
    def deviation_label(value: float | None) -> str:
        if value is None:
            return "—"
        absolute = abs(value)
        if absolute < 3:
            return "Yakın"
        if absolute < 7:
            return "Orta"
        if absolute < 12:
            return "Yüksek"
        return "Çok Yüksek"
