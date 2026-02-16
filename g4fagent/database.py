"""Database abstractions for g4fagent runtime and API state persistence.

Inputs:
- Backend selection and read/write requests for namespaced JSON-like payloads.
Output:
- A database backend implementation that stores and retrieves dictionary payloads.
Example:
```python
from pathlib import Path
from g4fagent.database import JSONDatabase

db = JSONDatabase(Path(".g4fagent_db"))
db.set("project", "state", {"status": "planning"})
```
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from abc import ABC, abstractmethod
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

DATABASE_BACKENDS = ("json", "sqlite", "mysql", "mariadb", "postgres", "mongo")


class Database(ABC):
    """Base persistence interface for JSON-serializable namespaced buckets."""

    @abstractmethod
    def read_bucket(self, bucket: str) -> Dict[str, Any]:
        """Read a bucket payload."""

    @abstractmethod
    def write_bucket(self, bucket: str, payload: Mapping[str, Any]) -> None:
        """Write a full bucket payload."""

    def get(self, bucket: str, key: str, default: Any = None) -> Any:
        data = self.read_bucket(bucket)
        if key not in data:
            return deepcopy(default)
        return deepcopy(data[key])

    def set(self, bucket: str, key: str, value: Any) -> None:
        data = self.read_bucket(bucket)
        data[str(key)] = deepcopy(value)
        self.write_bucket(bucket, data)

    def delete(self, bucket: str, key: str) -> None:
        data = self.read_bucket(bucket)
        if key in data:
            data.pop(key, None)
            self.write_bucket(bucket, data)


class JSONDatabase(Database):
    """File-backed JSON bucket storage (one JSON file per bucket)."""

    def __init__(self, root_dir: Union[str, Path]):
        self.root_dir = Path(root_dir).resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _bucket_path(self, bucket: str) -> Path:
        normalized = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(bucket).strip())
        if not normalized:
            raise ValueError("Bucket name cannot be empty.")
        return self.root_dir / f"{normalized}.json"

    def read_bucket(self, bucket: str) -> Dict[str, Any]:
        path = self._bucket_path(bucket)
        with self._lock:
            if not path.exists():
                return {}
            text = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(text)
        except Exception as exc:
            raise ValueError(f"Invalid JSON in database bucket: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Database bucket must contain a JSON object: {path}")
        return dict(payload)

    def write_bucket(self, bucket: str, payload: Mapping[str, Any]) -> None:
        data = dict(payload or {})
        path = self._bucket_path(bucket)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        encoded = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(encoded, encoding="utf-8")
            tmp_path.replace(path)


class SQLiteDatabase(Database):
    """SQLite-backed storage with one row per bucket."""

    def __init__(self, db_path: Union[str, Path]):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS buckets (
                        name TEXT PRIMARY KEY,
                        payload TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def read_bucket(self, bucket: str) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT payload FROM buckets WHERE name = ?",
                    (str(bucket),),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return {}
        payload = json.loads(str(row[0] or "{}"))
        if not isinstance(payload, dict):
            raise ValueError(f"SQLite bucket '{bucket}' contains non-object JSON payload.")
        return dict(payload)

    def write_bucket(self, bucket: str, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO buckets(name, payload)
                    VALUES (?, ?)
                    ON CONFLICT(name) DO UPDATE SET payload = excluded.payload
                    """,
                    (str(bucket), encoded),
                )
                conn.commit()
            finally:
                conn.close()


class _NotImplementedDatabase(Database):
    backend_name = "unknown"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def _raise(self) -> None:
        raise NotImplementedError(
            f"{self.backend_name} backend is declared but not implemented yet. "
            "Use 'json' for file-backed storage."
        )

    def read_bucket(self, bucket: str) -> Dict[str, Any]:
        _ = bucket
        self._raise()

    def write_bucket(self, bucket: str, payload: Mapping[str, Any]) -> None:
        _ = bucket
        _ = payload
        self._raise()


class MySQLDatabase(_NotImplementedDatabase):
    backend_name = "mysql"


class MariaDatabase(_NotImplementedDatabase):
    backend_name = "mariadb"


class PostgresDatabase(_NotImplementedDatabase):
    backend_name = "postgres"


class MongoDatabase(_NotImplementedDatabase):
    backend_name = "mongo"


def create_database(
    database: Optional[Union[str, Database]],
    *,
    base_dir: Optional[Path] = None,
) -> Optional[Database]:
    """Resolve a database backend from a backend string or instance."""
    if database is None:
        return None
    if isinstance(database, Database):
        return database

    backend = str(database).strip().lower()
    if not backend:
        return None

    resolved_base_dir = (base_dir or Path.cwd()).resolve()
    if backend in {"json", "jsondatabase"}:
        return JSONDatabase(resolved_base_dir / ".g4fagent_db")
    if backend in {"sqlite", "sqlitedatabase"}:
        return SQLiteDatabase(resolved_base_dir / ".g4fagent.sqlite3")
    if backend in {"mysql", "mysqldatabase"}:
        return MySQLDatabase()
    if backend in {"mariadb", "mariadbdatabase"}:
        return MariaDatabase()
    if backend in {"postgres", "postgresql", "postgresdatabase"}:
        return PostgresDatabase()
    if backend in {"mongo", "mongodb", "mongodatabase"}:
        return MongoDatabase()

    raise ValueError(f"Unknown database backend: {database!r}")
