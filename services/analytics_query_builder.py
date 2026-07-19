from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from services.core_analytics_engine import CoreAnalyticsEngine


@dataclass(slots=True)
class AnalyticsQueryBuilder:
    """Build parameterized WHERE clauses shared by analytics services."""

    clauses: list[str] = field(default_factory=list)
    parameters: list[Any] = field(default_factory=list)

    def add(self, sql: str, *parameters: Any) -> "AnalyticsQueryBuilder":
        if sql and sql.strip():
            self.clauses.append(sql.strip())
            self.parameters.extend(parameters)
        return self

    def site(self, value: str, column: str = "h.site") -> "AnalyticsQueryBuilder":
        value = str(value or "").strip()
        if value:
            self.add(f"TRIM({column}) = ?", value)
        return self

    def stakes(self, value: str, column: str = "h.stakes") -> "AnalyticsQueryBuilder":
        value = str(value or "").strip()
        if value:
            self.add(f"TRIM({column}) = ?", value)
        return self

    def position(self, value: str, column: str = "hp.position") -> "AnalyticsQueryBuilder":
        value = str(value or "").strip()
        if not value:
            return self
        aliases = CoreAnalyticsEngine.position_sql_values(value)
        placeholders = ", ".join("?" for _ in aliases)
        self.add(
            f"UPPER(TRIM({column})) IN ({placeholders})",
            *(alias.upper() for alias in aliases),
        )
        return self

    def player_like(self, value: str, expression: str) -> "AnalyticsQueryBuilder":
        value = str(value or "").strip().lower()
        if value:
            self.add(f"LOWER({expression}) LIKE ?", f"%{value}%")
        return self

    def one_of(self, values: Iterable[Any], column: str) -> "AnalyticsQueryBuilder":
        clean = [value for value in values if value is not None and str(value) != ""]
        if clean:
            placeholders = ", ".join("?" for _ in clean)
            self.add(f"{column} IN ({placeholders})", *clean)
        return self

    def render(self, prefix: str = "WHERE") -> tuple[str, list[Any]]:
        if not self.clauses:
            return "", list(self.parameters)
        return f"{prefix} " + " AND ".join(self.clauses), list(self.parameters)

    def render_and(self) -> tuple[str, list[Any]]:
        return self.render(prefix="AND")
