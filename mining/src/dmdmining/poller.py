"""Every minute: each pool's API read (all at once, each in its own thread), its figures kept, and
what changed made into events for the notifications:

  pool_down   a pool's API hasn't answered for 10 minutes, or its node is more than 5 blocks
              behind the chain for 10 minutes (its miners may be working on old blocks)
  pool_up     it answers again, its node caught up
  majority    one miner found more than half of the last 144 blocks (6 hours); majority_end when
              it's back under 45%

The minute figures are kept two days; their hourly averages for good.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from dmdmining import adapters, db
from dmdmining.catalog import Catalog, Pool

log = logging.getLogger(__name__)

PROBLEM_AFTER = 600
BEHIND_BLOCKS = 5
SAMPLE_SECONDS = 2 * 86400
POOL_BLOCKS_SECONDS = 31 * 86400
EVENTS_SECONDS = 7 * 86400
MAJORITY_BLOCKS = 144
MAJORITY_ON, MAJORITY_OFF = 0.5, 0.45
READERS = 8


def has_api(pool: Pool) -> bool:
    return bool(pool.api) and pool.software in ("MiningCore", "YIIMP")


def _event(conn: sqlite3.Connection, now: int, kind: str, slug: str | None, data: dict) -> None:
    conn.execute(
        "INSERT INTO events (time, kind, slug, data) VALUES (?, ?, ?, ?)",
        (now, kind, slug, json.dumps(data, separators=(",", ":"))),
    )


def tip(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT max(height) AS h FROM blocks").fetchone()
    return row["h"] if row else None


def record(
    conn: sqlite3.Connection, pool: Pool, figures: adapters.Figures, now: int, chain_tip: int | None
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM pool_state WHERE slug = ?", (pool.slug,)).fetchone()
    before: dict[str, Any] = json.loads(row["data"]) if row else {}
    api = has_api(pool)
    height = figures.height
    behind = (
        figures.ok
        and height is not None
        and chain_tip is not None
        and chain_tip - height > BEHIND_BLOCKS
    )
    if not api:
        problem = ""
    elif not figures.ok:
        problem = "down"
    elif behind:
        problem = "behind"
    else:
        problem = ""
    since = before.get("problem_since") if before.get("problem") == problem and problem else None
    since = since or (now if problem else None)
    told = before.get("told", "")
    if api and problem and now - since >= PROBLEM_AFTER and told != problem:
        _event(
            conn,
            now,
            "pool_down",
            pool.slug,
            {"reason": problem, "error": figures.error, "height": height, "tip": chain_tip},
        )
        told = problem
    elif api and not problem and told in ("down", "behind"):
        _event(conn, now, "pool_up", pool.slug, {"was": told})
        told = ""
    hashrate = figures.total("hashrate")
    miners = figures.total("miners")
    workers = figures.total("workers")
    state = {
        "api": api,
        "ok": figures.ok,
        "error": figures.error if api else "",
        "problem": problem,
        "problem_since": since,
        "told": told,
        "hashrate": hashrate,
        "miners": int(miners) if miners is not None else None,
        "workers": int(workers) if workers is not None else None,
        "height": height,
        "modes": [m.public() for m in figures.modes],
        "checked_at": now,
    }
    ok_at = now if figures.ok else (row["ok_at"] if row else None)
    fail_since = None if figures.ok else ((row["fail_since"] if row else None) or now)
    conn.execute(
        "INSERT INTO pool_state (slug, data, ok_at, fail_since, error, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (slug) DO UPDATE SET data = excluded.data, "
        "ok_at = excluded.ok_at, fail_since = excluded.fail_since, error = excluded.error, "
        "updated_at = excluded.updated_at",
        (
            pool.slug,
            json.dumps(state, separators=(",", ":")),
            ok_at,
            fail_since,
            figures.error or None,
            now,
        ),
    )
    if api:
        conn.execute(
            "INSERT OR REPLACE INTO samples (slug, t, ok, hashrate, miners, workers, height) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                pool.slug,
                now - now % 60,
                1 if figures.ok else 0,
                hashrate if figures.ok else None,
                state["miners"],
                state["workers"],
                height,
            ),
        )
    for b in figures.blocks:
        conn.execute(
            "INSERT INTO pool_blocks (slug, mode, height, hash, status, effort, reward, created, "
            "miner) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (slug, height, hash) DO UPDATE "
            "SET status = excluded.status, effort = coalesce(excluded.effort, pool_blocks.effort), "
            "reward = coalesce(excluded.reward, pool_blocks.reward), mode = excluded.mode",
            (
                pool.slug,
                b["mode"],
                b["height"],
                b["hash"],
                b["status"],
                b["effort"],
                b["reward"],
                b["created"],
                b["miner"],
            ),
        )
    return state


def poll(conn: sqlite3.Connection, catalog: Catalog, now: int) -> dict[str, dict[str, Any]]:
    """Reads every pool's API once, and keeps what each said."""
    due = db.get(conn, "blocks_read_at", {})
    pools = list(catalog.pools)

    def one(pool: Pool) -> tuple[Pool, adapters.Figures]:
        blocks_due = now - int(due.get(pool.slug, 0)) >= adapters.BLOCKS_EVERY
        return pool, adapters.read(pool, now, blocks_due)

    with ThreadPoolExecutor(max_workers=READERS, thread_name_prefix="pool") as pool_threads:
        results = list(pool_threads.map(one, pools))
    chain_tip = tip(conn)
    states = {}
    conn.execute("BEGIN")
    try:
        for pool, figures in results:
            states[pool.slug] = record(conn, pool, figures, now, chain_tip)
            read_blocks = figures.ok and pool.software == "MiningCore"
            if read_blocks and now - int(due.get(pool.slug, 0)) >= adapters.BLOCKS_EVERY:
                due[pool.slug] = now
        db.put(conn, "blocks_read_at", due)
        db.put(conn, "polled_at", now)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    broken = [p.slug for p, f in results if has_api(p) and not f.ok]
    if broken:
        log.debug("not answering: %s", ", ".join(broken))
    return states


def majority(conn: sqlite3.Connection, now: int) -> None:
    rows = conn.execute(
        "SELECT coalesce(slug, miner) AS who, max(slug) AS slug, max(miner) AS miner, "
        "count(*) AS n "
        "FROM (SELECT slug, miner FROM blocks ORDER BY height DESC LIMIT ?) GROUP BY who "
        "ORDER BY n DESC",
        (MAJORITY_BLOCKS,),
    ).fetchall()
    total = sum(r["n"] for r in rows)
    if total < MAJORITY_BLOCKS:
        return
    top = rows[0]
    share = top["n"] / total
    on = db.get(conn, "majority")
    if on is None and share > MAJORITY_ON:
        data = {
            "who": top["who"],
            "slug": top["slug"],
            "miner": top["miner"],
            "share": round(share, 4),
            "blocks": top["n"],
            "of": total,
        }
        _event(conn, now, "majority", top["slug"], data)
        db.put(conn, "majority", data)
    elif on is not None:
        mine = next((r for r in rows if r["who"] == on["who"]), None)
        current = (mine["n"] / total) if mine else 0.0
        if current < MAJORITY_OFF:
            _event(conn, now, "majority_end", on.get("slug"), {**on, "share": round(current, 4)})
            conn.execute("DELETE FROM state WHERE key = 'majority'")


def aggregate(conn: sqlite3.Connection, now: int) -> None:
    """The finished hours' averages; the old minute figures, blocks and events go."""
    done = int(db.get(conn, "hourly_done", 0))
    hour = now - now % 3600
    first = conn.execute("SELECT min(t) AS t FROM samples WHERE t >= ?", (done,)).fetchone()["t"]
    if first is not None:
        start = max(done, first - first % 3600)
        if start < hour:
            conn.execute(
                "INSERT OR REPLACE INTO hourly (slug, t, hashrate, miners, ok, n) "
                "SELECT slug, t - t % 3600, avg(CASE WHEN ok THEN hashrate END), "
                "avg(CASE WHEN ok THEN miners END), avg(ok), count(*) FROM samples "
                "WHERE t >= ? AND t < ? GROUP BY slug, t - t % 3600",
                (start, hour),
            )
    db.put(conn, "hourly_done", hour)
    conn.execute("DELETE FROM samples WHERE t < ?", (now - SAMPLE_SECONDS,))
    conn.execute("DELETE FROM pool_blocks WHERE created < ?", (now - POOL_BLOCKS_SECONDS,))
    conn.execute("DELETE FROM events WHERE time < ?", (now - EVENTS_SECONDS,))
