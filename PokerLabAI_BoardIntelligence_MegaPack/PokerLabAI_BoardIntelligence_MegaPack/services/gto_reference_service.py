from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class GTOReferenceService:
    """Persistent user-entered GTO frequencies stored outside the hand database."""

    def __init__(self, path: str = "database/gto_board_references.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(site: str, stakes: str, board_family: str, street: str, metric: str) -> str:
        return "|".join([
            (site or "ALL").strip(), (stakes or "ALL").strip(),
            (board_family or "ALL").strip(), (street or "ALL").strip().upper(),
            metric.strip().upper(),
        ])

    def _load(self) -> dict[str, float]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(k): float(v) for k, v in raw.items() if v is not None}
        except Exception:
            return {}

    def get(self, site: str, stakes: str, board_family: str, street: str, metric: str) -> float | None:
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

    def set(self, site: str, stakes: str, board_family: str, street: str, metric: str, value: float | None) -> None:
        data = self._load()
        key = self._key(site, stakes, board_family, street, metric)
        if value is None:
            data.pop(key, None)
        else:
            data[key] = max(0.0, min(100.0, float(value)))
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.path)

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
