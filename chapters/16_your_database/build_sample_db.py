"""A tiny sample SQLite database, built with the standard library.

    python chapters/16_your_database/build_sample_db.py

Chapter 16 lets the agent query *your* database. To have something to point it at
out of the box — with real foreign keys, so the ER diagram has edges to draw — we
build a three-table shop here. It's deliberately small and deterministic so the
tests and the README's numbers stay fixed. No binary is committed; this script is
the source of truth, which also shows exactly how little a "database" needs to be.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "sample_shop.sqlite"

_SCHEMA = """
CREATE TABLE customers (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT
);
CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    total       REAL NOT NULL,
    status      TEXT
);
CREATE TABLE line_items (
    id       INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    sku      TEXT,
    qty      INTEGER
);
"""

_CUSTOMERS = [(1, "Alice", "Berlin"), (2, "Bob", "Hamburg"), (3, "Carol", "Berlin")]
# Totals per customer: Alice 150, Bob 220, Carol 50 → Bob is the top spender.
_ORDERS = [
    (1, 1, 120.0, "paid"),
    (2, 1, 30.0, "paid"),
    (3, 2, 200.0, "paid"),
    (4, 3, 50.0, "pending"),
    (5, 2, 20.0, "paid"),
]
_LINE_ITEMS = [
    (1, 1, "A100", 2),
    (2, 1, "B200", 1),
    (3, 3, "A100", 5),
    (4, 2, "C300", 1),
    (5, 5, "B200", 3),
]


def build(path: Path = DEFAULT_DB) -> Path:
    """(Re)create the sample database at `path`. Overwrites if it exists."""
    path = Path(path)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(_SCHEMA)
        con.executemany("INSERT INTO customers VALUES (?,?,?)", _CUSTOMERS)
        con.executemany("INSERT INTO orders VALUES (?,?,?,?)", _ORDERS)
        con.executemany("INSERT INTO line_items VALUES (?,?,?,?)", _LINE_ITEMS)
        con.commit()
    finally:
        con.close()
    return path


def ensure(path: Path = DEFAULT_DB) -> Path:
    """Build the sample database only if it isn't there yet."""
    path = Path(path)
    if not path.exists():
        build(path)
    return path


if __name__ == "__main__":
    p = build()
    print(f"built {p} ({p.stat().st_size} bytes)")
