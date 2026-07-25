"""SQLite persistence for product stock state.

One row per monitored product URL. Stores the last known stock state so the
checker can fire notifications only on an Out-of-Stock -> In-Stock transition,
and records timestamps/price for history and future analytics.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProductRecord:
    id: int
    url: str
    retailer: str
    name: str | None
    in_stock: bool
    price: str | None
    last_checked: float | None
    last_alert: float | None
    enabled: bool


_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL UNIQUE,
    retailer      TEXT NOT NULL,
    name          TEXT,
    in_stock      INTEGER NOT NULL DEFAULT 0,
    price         TEXT,
    last_checked  REAL,
    last_alert    REAL,
    created       REAL NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(products)").fetchall()
        }
        if "enabled" not in columns:
            self._conn.execute(
                "ALTER TABLE products ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get(self, url: str) -> ProductRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM products WHERE url = ?", (url,)
            ).fetchone()
        if row is None:
            return None
        return ProductRecord(
            id=row["id"],
            url=row["url"],
            retailer=row["retailer"],
            name=row["name"],
            in_stock=bool(row["in_stock"]),
            price=row["price"],
            last_checked=row["last_checked"],
            last_alert=row["last_alert"],
            enabled=bool(row["enabled"]),
        )

    def ensure(self, url: str, retailer: str, name: str | None = None) -> None:
        """Insert a placeholder row for a product if it does not yet exist."""
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO products
                   (url, retailer, name, created) VALUES (?, ?, ?, ?)""",
                (url, retailer, name, time.time()),
            )
            self._conn.commit()

    def add(self, url: str, retailer: str, name: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO products (url, retailer, name, created, enabled)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(url) DO UPDATE SET
                    retailer = excluded.retailer,
                    name = excluded.name,
                    enabled = 1
                """,
                (url, retailer, name, time.time()),
            )
            self._conn.commit()

    def remove(self, product_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM products WHERE id = ?", (product_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def update_state(
        self,
        url: str,
        *,
        name: str | None,
        in_stock: bool,
        price: str | None,
        alerted: bool,
    ) -> None:
        now = time.time()
        # COALESCE keeps an existing name/price if this check could not resolve one.
        with self._lock:
            self._conn.execute(
                """
            UPDATE products
               SET name         = COALESCE(?, name),
                   in_stock     = ?,
                   price        = COALESCE(?, price),
                   last_checked = ?,
                   last_alert   = CASE WHEN ? THEN ? ELSE last_alert END
             WHERE url = ?
            """,
                (name, int(in_stock), price, now, int(alerted), now, url),
            )
            self._conn.commit()

    def all(self) -> list[ProductRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM products ORDER BY retailer, url"
            ).fetchall()
        return [
            ProductRecord(
                id=r["id"],
                url=r["url"],
                retailer=r["retailer"],
                name=r["name"],
                in_stock=bool(r["in_stock"]),
                price=r["price"],
                last_checked=r["last_checked"],
                last_alert=r["last_alert"],
                enabled=bool(r["enabled"]),
            )
            for r in rows
        ]

    def active(self) -> list[ProductRecord]:
        return [product for product in self.all() if product.enabled]
