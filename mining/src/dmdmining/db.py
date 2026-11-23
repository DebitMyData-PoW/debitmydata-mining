"""The database: one SQLite file (DMDM_DATA_DIR/mining.sqlite3), small enough for a 1 GB server.

blocks       every block since block 1, and who found it (as DMD Stats names it)
samples      each pool's figures from its API, once a minute, for two days
hourly       their hourly averages, kept for good (a few kilobytes a day)
pool_state   each pool's last answer from its API, and since when it fails
pool_blocks  the blocks each pool's API lists (status, effort), for a month
events       what the notifications tell (a block found, a pool down, one pool with most blocks)
devices      the devices with notifications on: their browser's subscription and choices
state        small values kept between runs
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS blocks (
    height INTEGER PRIMARY KEY,
    hash TEXT NOT NULL,
    time INTEGER NOT NULL,
    difficulty REAL NOT NULL,
    miner TEXT NOT NULL,
    slug TEXT,
    tx INTEGER,
    size INTEGER,
    reward REAL
);
CREATE INDEX IF NOT EXISTS blocks_time ON blocks (time);
CREATE INDEX IF NOT EXISTS blocks_slug ON blocks (slug, height);
CREATE INDEX IF NOT EXISTS blocks_slug_time ON blocks (slug, time);
CREATE TABLE IF NOT EXISTS samples (
    slug TEXT NOT NULL,
    t INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    hashrate REAL,
    miners INTEGER,
    workers INTEGER,
    height INTEGER,
    PRIMARY KEY (slug, t)
);
CREATE TABLE IF NOT EXISTS hourly (
    slug TEXT NOT NULL,
    t INTEGER NOT NULL,
    hashrate REAL,
    miners REAL,
    ok REAL NOT NULL,
    n INTEGER NOT NULL,
    PRIMARY KEY (slug, t)
);
CREATE TABLE IF NOT EXISTS pool_state (
    slug TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    ok_at INTEGER,
    fail_since INTEGER,
    error TEXT,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS pool_blocks (
    slug TEXT NOT NULL,
    mode TEXT NOT NULL,
    height INTEGER NOT NULL,
    hash TEXT NOT NULL,
    status TEXT NOT NULL,
    effort REAL,
    reward REAL,
    created INTEGER,
    miner TEXT,
    PRIMARY KEY (slug, height, hash)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time INTEGER NOT NULL,
    kind TEXT NOT NULL,
    slug TEXT,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    endpoint TEXT NOT NULL,
    endpoint_hash TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    prefs TEXT NOT NULL,
    cursor INTEGER NOT NULL DEFAULT 0,
    sent TEXT NOT NULL DEFAULT '[]',
    failures INTEGER NOT NULL DEFAULT 0,
    test_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """A connection (one per thread), its rows readable by column name. WAL: the notifications'
    API reads while the service writes."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    if str(path) != ":memory:":
        # (It holds the devices' push addresses: for this server's user only. SQLite gives its
        # -wal and -shm files the same permissions.)
        os.chmod(path, 0o600)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def get(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return default


def put(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO state (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, separators=(",", ":"))),
    )
