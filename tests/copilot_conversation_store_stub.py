"""In-memory Supabase stub for Ask Cadivor persistence harnesses/tests."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemoryCopilotStore:
    """Minimal Supabase table stub for copilot_conversation_threads."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}

    def clear(self) -> None:
        self.rows.clear()

    def table(self, name: str) -> "_TableQuery":
        if name != "copilot_conversation_threads":
            raise KeyError(f"Unsupported table: {name}")
        return _TableQuery(self)


class _TableQuery:
    def __init__(self, store: InMemoryCopilotStore) -> None:
        self._store = store
        self._select_fields = "*"
        self._filters: list[tuple[str, Any]] = []
        self._limit: int | None = None
        self._payload: dict[str, Any] | None = None
        self._upsert_conflict: str | None = None
        self._mode = "select"

    def select(self, fields: str) -> "_TableQuery":
        self._select_fields = fields
        self._mode = "select"
        return self

    def eq(self, field: str, value: Any) -> "_TableQuery":
        self._filters.append((field, value))
        return self

    def limit(self, count: int) -> "_TableQuery":
        self._limit = count
        return self

    def upsert(self, payload: dict[str, Any], *, on_conflict: str) -> "_TableQuery":
        self._payload = deepcopy(payload)
        self._upsert_conflict = on_conflict
        self._mode = "upsert"
        return self

    def delete(self) -> "_TableQuery":
        self._mode = "delete"
        return self

    def execute(self) -> Any:
        if self._mode == "select":
            return _Response(self._matched_rows())
        if self._mode == "upsert":
            return _Response([self._upsert_row()])
        if self._mode == "delete":
            for key in list(self._store.rows):
                row = self._store.rows[key]
                if self._matches(row):
                    del self._store.rows[key]
            return _Response([])
        raise RuntimeError(f"Unsupported query mode: {self._mode}")

    def _matched_rows(self) -> list[dict[str, Any]]:
        rows = [deepcopy(row) for row in self._store.rows.values() if self._matches(row)]
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._select_fields == "thread":
            return [{"thread": row.get("thread", [])} for row in rows]
        return rows

    def _matches(self, row: dict[str, Any]) -> bool:
        return all(str(row.get(field)) == str(value) for field, value in self._filters)

    def _upsert_row(self) -> dict[str, Any]:
        payload = dict(self._payload or {})
        user_id = str(payload.get("user_id") or "")
        analysis_id = str(payload.get("analysis_id") or "")
        key = (user_id, analysis_id)
        self._store.rows[key] = deepcopy(payload)
        return deepcopy(payload)


class _Response:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data
