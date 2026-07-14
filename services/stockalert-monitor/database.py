"""SQLite persistence for product stock state.

One row per monitored product URL. Stores the last known stock state so the
checker can fire notifications only on an Out-of-Stock -> In-Stock transition,
and records timestamps/price for history and future analytics.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProductRecord:
    url: str
    retailer: str
    name: str | None
    in_stock: bool
    price: str | None
    last_checked: float | None
    last_alert: float | None


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
    created       REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get(self, url: str) -> ProductRecord | None:
        row = self._conn.execute(
            "SELECT * FROM products WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return None
        return ProductRecord(
            url=row["url"],
            retailer=row["retailer"],
            name=row["name"],
            in_stock=bool(row["in_stock"]),
            price=row["price"],
            last_checked=row["last_checked"],
            last_alert=row["last_alert"],
        )

    def ensure(self, url: str, retailer: str) -> None:
        """Insert a placeholder row for a product if it does not yet exist."""
        self._conn.execute(
            "INSERT OR IGNORE INTO products (url, retailer, created) VALUES (?, ?, ?)",
            (url, retailer, time.time()),
        )
        self._conn.commit()

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
        rows = self._conn.execute(
            "SELECT * FROM products ORDER BY retailer, url"
        ).fetchall()
        return [
            ProductRecord(
                url=r["url"],
                retailer=r["retailer"],
                name=r["name"],
                in_stock=bool(r["in_stock"]),
                price=r["price"],
                last_checked=r["last_checked"],
                last_alert=r["last_alert"],
            )
            for r in rows
        ]
