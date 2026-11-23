"""The chain's side: every block and who found it, from DMD Stats (stats.debitmydata.io), which
keeps every block since block 1 from its own node and names its miner from DebitMyData's pool list
(the text the block's coinbase writes, or the address it pays). This server needs no node.

  api/blocks.json      the last 1,000 blocks, read every 20 seconds (DMDM_CHAIN_SECONDS): the new
                       ones, and any replaced by a reorganization
  api/dmd-blocks.csv   every block, read once at the start, then every 6 hours: a changed pool
                       list names old blocks again

A new block is an event: the notifications tell the devices following its pool.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from dmdmining import db, fetch
from dmdmining.catalog import Catalog

log = logging.getLogger(__name__)

BLOCK_SECONDS = 150
HASHES_PER_DIFFICULTY = 2**32
INITIAL_SUBSIDY = 35.0
HALVING_BLOCKS = 300_000
SUBSIDY_CYCLE_BLOCKS = 9_600_000
FULL_SYNC_SECONDS = 6 * 3600
OFFICIAL_MINER = "the DebitMyData pool"  # DMD Stats' name for the pool's blocks
NEW_BLOCK_DEPTH = 6  # a block replaced this close to the tip is told about as a new one


def subsidy(height: int) -> float:
    """New DMD in the block at this height (DebitMyData Core's GetBlockSubsidy)."""
    halvings = (height % SUBSIDY_CYCLE_BLOCKS) // HALVING_BLOCKS
    return 0.0 if halvings >= 64 else INITIAL_SUBSIDY / (2**halvings)


def slug_for(miner: str, catalog: Catalog) -> str | None:
    if miner == OFFICIAL_MINER:
        return "official"
    for pool in catalog.pools:
        if pool.name == miner:
            return pool.slug
    return None


def _clean(row: dict[str, Any]) -> tuple[Any, ...] | None:
    try:
        height = int(row["height"])
        block_hash = str(row["hash"])
        if height < 0 or len(block_hash) != 64:
            return None
        slug = row.get("slug")
        reward = row.get("reward")
        return (
            height,
            block_hash,
            int(row["time"]),
            float(row["difficulty"]),
            str(row.get("miner") or "unknown")[:100],
            slug if isinstance(slug, str) and slug else None,
            int(row["tx"]) if row.get("tx") is not None else None,
            int(row["size"]) if row.get("size") is not None else None,
            float(reward) if reward is not None else None,
        )
    except (KeyError, TypeError, ValueError):
        return None


def store(conn: sqlite3.Connection, rows: list[dict[str, Any]], now: int, tell: bool = True) -> int:
    """Keeps these blocks (new ones, or ones whose hash changed: a reorganization replaced them).
    Returns how many were new or replaced; with `tell`, the ones near the tip become events."""
    clean = [r for r in (_clean(x) for x in rows) if r is not None]
    if not clean:
        return 0
    tip_row = conn.execute("SELECT max(height) AS h FROM blocks").fetchone()
    tip = tip_row["h"] if tip_row and tip_row["h"] is not None else None
    heights = [r[0] for r in clean]
    known = {
        r["height"]: (r["hash"], r["miner"], r["slug"], r["reward"])
        for r in conn.execute(
            "SELECT height, hash, miner, slug, reward FROM blocks WHERE height BETWEEN ? AND ?",
            (min(heights), max(heights)),
        )
    }
    changed = 0
    conn.execute("BEGIN")
    try:
        for r in sorted(clean):
            old = known.get(r[0])
            if old is not None and old == (r[1], r[4], r[5], r[8]):
                continue
            conn.execute(
                "INSERT INTO blocks (height, hash, time, difficulty, miner, slug, tx, size, "
                "reward) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (height) DO UPDATE SET "
                "hash = excluded.hash, time = excluded.time, difficulty = excluded.difficulty, "
                "miner = excluded.miner, slug = excluded.slug, tx = excluded.tx, "
                "size = excluded.size, reward = coalesce(excluded.reward, blocks.reward)",
                r,
            )
            new_hash = old is None or old[0] != r[1]
            if not new_hash:
                continue  # named again (the pool list changed): not a new block
            changed += 1
            if tell and tip is not None and r[0] > tip - NEW_BLOCK_DEPTH:
                conn.execute(
                    "INSERT INTO events (time, kind, slug, data) VALUES (?, 'block', ?, ?)",
                    (
                        now,
                        r[5],
                        json.dumps(
                            {"height": r[0], "hash": r[1], "miner": r[4], "time": r[2]},
                            separators=(",", ":"),
                        ),
                    ),
                )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return changed


def read_latest(stats_url: str) -> list[dict[str, Any]]:
    data = fetch.get_json(f"{stats_url}/api/blocks.json", limit=2_000_000)
    blocks = data.get("blocks") if isinstance(data, dict) else None
    if not isinstance(blocks, list):
        raise fetch.FetchError("blocks.json has no blocks")
    out = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        out.append(
            {
                "height": b.get("height"),
                "hash": b.get("hash"),
                "time": b.get("time"),
                "difficulty": b.get("difficulty"),
                "miner": b.get("miner"),
                "slug": b.get("slug"),
                "tx": b.get("transactions"),
                "size": b.get("size"),
                "reward": b.get("reward_dmd"),
            }
        )
    return out


def read_all(stats_url: str, catalog: Catalog) -> list[dict[str, Any]]:
    body = fetch.get(f"{stats_url}/api/dmd-blocks.csv", timeout=120, limit=400_000_000)
    out = []
    for row in csv.DictReader(io.StringIO(body.decode("utf-8", "replace"))):
        try:
            height = int(row["height"])
            when = int(datetime.fromisoformat(row["time_utc"].replace("Z", "+00:00")).timestamp())
        except (KeyError, ValueError):
            continue
        miner = row.get("miner") or ("the DebitMyData pool" if row.get("pool") == "1" else "")
        fees = row.get("fees_dmd")
        try:
            reward = subsidy(height) + float(fees) if fees not in (None, "") else None
        except ValueError:
            reward = None
        out.append(
            {
                "height": height,
                "hash": row.get("hash"),
                "time": when,
                "difficulty": row.get("difficulty"),
                "miner": miner or "unknown",
                "slug": slug_for(miner, catalog),
                "tx": row.get("transactions") or None,
                "size": row.get("size_bytes") or None,
                "reward": reward,
            }
        )
    return out


def follow(conn: sqlite3.Connection, stats_url: str, catalog: Catalog, now: int) -> int:
    """One round: every block once at the start and every 6 hours, the latest ones every time.
    Returns how many blocks were new (or replaced)."""
    new = 0
    empty = conn.execute("SELECT count(*) AS n FROM blocks").fetchone()["n"] == 0
    last_full = db.get(conn, "chain_full_sync", 0)
    if empty or now - last_full >= FULL_SYNC_SECONDS:
        try:
            rows = read_all(stats_url, catalog)
            n = store(conn, rows, now, tell=False)
            new += n
            db.put(conn, "chain_full_sync", now)
            if n:
                log.info("every block read from DMD Stats: %d new or named again", n)
        except fetch.FetchError as exc:
            log.warning("every block: DMD Stats did not answer (%s)", exc)
    rows = read_latest(stats_url)
    new += store(conn, rows, now, tell=not empty)
    db.put(conn, "chain_read_at", now)
    return new
