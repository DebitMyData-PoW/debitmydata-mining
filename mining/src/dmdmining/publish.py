"""The site's files, which are its API too (mining.debitmydata.io/api/ explains them). Written
every 20 seconds when something changed, the long charts every 10 minutes.

  api/summary.json          the network, every pool (its API's figures, its blocks, its status),
                            the other miners, how concentrated the mining is
  api/blocks.json           the last 100 blocks and who found them
  api/distribution.json     who found the blocks: the last 24 hours, 7 days, 30 days, year, ever,
                            and the last 1,000 blocks
  api/chart-<range>.json    the pools' hashrate (from their APIs) and the network's (from the
                            chain), and the blocks each found, over time: 24h, 7d, 30d, 1y, all
  api/pools/<slug>.json     one pool: how to connect, its figures, its charts, its blocks

Hashrate of the network, or of a pool from its blocks: the work of the blocks found (difficulty ×
2^32 each) divided by the time. A pool's own hashrate: what its API says. Luck: the blocks a pool
found against those its hashrate should have found at the difficulty of the time.
"""

from __future__ import annotations

import bisect
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dmdmining import __version__, chain, db
from dmdmining.catalog import Catalog, Pool, country_code

HOUR, DAY = 3600, 86400
WORK = chain.HASHES_PER_DIFFICULTY
SLOW_RANGES = {"30d": 600, "1y": 600, "all": 600}
#: range: (span, hashrate step, network window, blocks step)
RANGES = {
    "24h": (DAY, 300, 2 * HOUR, HOUR),
    "7d": (7 * DAY, HOUR, 3 * HOUR, 6 * HOUR),
    "30d": (30 * DAY, 6 * HOUR, 6 * HOUR, DAY),
    "1y": (365 * DAY, DAY, DAY, 7 * DAY),
    "all": (0, DAY, DAY, 7 * DAY),
}
PERIODS = {"1h": HOUR, "24h": DAY, "7d": 7 * DAY, "30d": 30 * DAY}
TOP_SERIES = 8
COLORS = 7


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def _round(value: float | None, places: int = 0) -> float | None:
    if value is None:
        return None
    return round(value, places) if places else float(round(value))


@dataclass
class Chain:
    """Every block's time and work, in order, for the hashrates (a block found at t did the work
    of its difficulty)."""

    heights: list[int]
    times: list[int]
    work: list[float]
    prefix: list[float]  # prefix[i]: the work of blocks before i
    sorted_times: list[int]
    order: list[int]  # the blocks in time order (times aren't always in height order)
    sorted_prefix: list[float]

    @classmethod
    def load(cls, conn: sqlite3.Connection) -> Chain:
        rows = conn.execute(
            "SELECT height, time, difficulty FROM blocks ORDER BY height"
        ).fetchall()
        heights = [r["height"] for r in rows]
        times = [r["time"] for r in rows]
        work = [r["difficulty"] * WORK for r in rows]
        prefix = [0.0]
        for w in work:
            prefix.append(prefix[-1] + w)
        order = sorted(range(len(times)), key=lambda i: times[i])
        sorted_prefix = [0.0]
        for i in order:
            sorted_prefix.append(sorted_prefix[-1] + work[i])
        return cls(heights, times, work, prefix, [times[i] for i in order], order, sorted_prefix)

    def work_between(self, start: float, end: float) -> float:
        """The work of the blocks found after `start`, up to `end`."""
        a = bisect.bisect_right(self.sorted_times, start)
        b = bisect.bisect_right(self.sorted_times, end)
        return self.sorted_prefix[b] - self.sorted_prefix[a]

    def hashrate(self, end: float, window: float) -> float | None:
        if not self.times or window <= 0:
            return None
        return self.work_between(end - window, end) / window


def _blocks_by(conn: sqlite3.Connection, since: int, limit: int | None = None) -> list[sqlite3.Row]:
    if limit:
        return conn.execute(
            "SELECT coalesce(slug, '~' || miner) AS who, slug, miner, count(*) AS n, "
            "max(height) AS last FROM (SELECT slug, miner, height FROM blocks ORDER BY height DESC "
            "LIMIT ?) GROUP BY who ORDER BY n DESC",
            (limit,),
        ).fetchall()
    return conn.execute(
        "SELECT coalesce(slug, '~' || miner) AS who, slug, miner, count(*) AS n, "
        "max(height) AS last FROM blocks WHERE time > ? GROUP BY who ORDER BY n DESC",
        (since,),
    ).fetchall()


def nakamoto(counts: list[int]) -> int | None:
    """How many miners together found more than half of the blocks (the fewer, the easier a few
    could rewrite the chain)."""
    total = sum(counts)
    if not total:
        return None
    running = 0
    for n, count in enumerate(sorted(counts, reverse=True), 1):
        running += count
        if running * 2 > total:
            return n
    return len(counts)


def _name(slug: str | None, miner: str, pools: dict[str, Pool]) -> str:
    if slug and slug in pools:
        return pools[slug].display
    if miner == chain.OFFICIAL_MINER:
        return "DebitMyData pool"
    return miner


def _flag(code: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code) if len(code) == 2 else ""


def stratum_urls(pool: Pool, mode: dict[str, Any]) -> list[dict[str, Any]]:
    """Where miners connect: the API's ports on the pool's stratum servers (MiningCore), else the
    addresses pools-info.json gives."""
    out = []
    hosts = list(pool.hosts) or ([pool.domain] if pool.domain else [])
    for port in mode.get("ports") or []:
        scheme = "stratum+ssl" if port.get("tls") else "stratum+tcp"
        for host in hosts:
            out.append({**port, "host": host, "url": f"{scheme}://{host}:{port['port']}"})
    if not out:
        for address in mode.get("stratum") or []:
            host, _, port = address.rpartition(":")
            out.append(
                {
                    "host": host,
                    "port": int(port) if port.isdigit() else None,
                    "difficulty": None,
                    "vardiff": None,
                    "tls": False,
                    "name": None,
                    "url": f"stratum+tcp://{address}",
                }
            )
    return out[:30]


def _spark(conn: sqlite3.Connection, slug: str, now: int, api: bool) -> list[float | None]:
    """The last 24 hours, an hour each: its hashrate (API), else its blocks."""
    start = now - now % HOUR - 23 * HOUR
    values: dict[int, float | None] = {}
    if api:
        for r in conn.execute(
            "SELECT t - t % 3600 AS h, avg(hashrate) AS v FROM samples WHERE slug = ? AND ok "
            "AND t >= ? GROUP BY h",
            (slug, start),
        ):
            values[r["h"]] = r["v"]
    else:
        for r in conn.execute(
            "SELECT time - time % 3600 AS h, count(*) AS v FROM blocks WHERE slug = ? "
            "AND time >= ? GROUP BY h",
            (slug, start),
        ):
            values[r["h"]] = r["v"]
    out = []
    for k in range(24):
        v = values.get(start + k * HOUR)
        out.append(_round(v) if v is not None else (None if api else 0))
    return out


def _reported(conn: sqlite3.Connection, slug: str, since: int) -> tuple[float | None, int, int]:
    """A pool's average hashrate (its API) since then, from the hourly figures and the minute
    ones not yet in them; and how many minutes it answered, of how many it was asked."""
    done = int(db.get(conn, "hourly_done", 0))
    h = conn.execute(
        "SELECT sum(hashrate * ok * n) AS w, sum(ok * n) AS good, sum(n) AS n FROM hourly "
        "WHERE slug = ? AND t >= ? AND t < ?",
        (slug, since, done),
    ).fetchone()
    s = conn.execute(
        "SELECT sum(CASE WHEN ok THEN hashrate END) AS w, sum(ok) AS good, count(*) AS n, "
        "sum(CASE WHEN ok AND hashrate IS NOT NULL THEN 1 END) AS counted FROM samples "
        "WHERE slug = ? AND t >= ?",
        (slug, max(since, done)),
    ).fetchone()
    weight = (h["w"] or 0.0) + (s["w"] or 0.0)
    counted = (h["good"] or 0) + (s["counted"] or 0)
    good = round((h["good"] or 0) + (s["good"] or 0))
    asked = (h["n"] or 0) + (s["n"] or 0)
    return (weight / counted if counted else None), good, asked


def _luck(
    c: Chain, found: int, reported: float | None, answered: int, start: int, end: int
) -> float | None:
    """Blocks found ÷ blocks its hashrate should have found (needs its API for at least half of
    that time)."""
    if not reported or end <= start or answered * 60 < (end - start) / 2:
        return None
    work = c.work_between(start, end)
    blocks = bisect.bisect_right(c.sorted_times, end) - bisect.bisect_right(c.sorted_times, start)
    if not blocks or not work:
        return None
    expected = reported * (end - start) / (work / blocks)
    return round(found / expected, 4) if expected > 0 else None


def _uptime(conn: sqlite3.Connection, slug: str, since: int) -> float | None:
    """The share of the times its API was asked that it answered."""
    _, good, asked = _reported(conn, slug, since)
    return round(good / asked, 4) if asked else None


def pool_entry(
    conn: sqlite3.Connection,
    pool: Pool,
    c: Chain,
    now: int,
    network_24h: float | None,
    has_logo: bool,
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM pool_state WHERE slug = ?", (pool.slug,)).fetchone()
    state = json.loads(row["data"]) if row else {}
    api = bool(state.get("api"))
    blocks = {
        name: conn.execute(
            "SELECT count(*) AS n FROM blocks WHERE slug = ? AND time > ?", (pool.slug, now - span)
        ).fetchone()["n"]
        for name, span in PERIODS.items()
    }
    totals = conn.execute(
        "SELECT count(*) AS n, min(height) AS first, max(height) AS last, sum(reward) AS mined "
        "FROM blocks WHERE slug = ?",
        (pool.slug,),
    ).fetchone()
    last = (
        conn.execute(
            "SELECT height, time, hash FROM blocks WHERE slug = ? ORDER BY height DESC LIMIT 1",
            (pool.slug,),
        ).fetchone()
        if totals["n"]
        else None
    )
    first = (
        conn.execute(
            "SELECT height, time FROM blocks WHERE height = ?", (totals["first"],)
        ).fetchone()
        if totals["n"]
        else None
    )
    own_work = sum(
        r["d"] * WORK
        for r in conn.execute(
            "SELECT difficulty AS d FROM blocks WHERE slug = ? AND time > ?", (pool.slug, now - DAY)
        )
    )
    reported_24h, answered_24h, _ = _reported(conn, pool.slug, now - DAY)
    modes = state.get("modes") or [
        {
            "label": m.label,
            "scheme": m.scheme,
            "fee": m.fee,
            "min_payout": m.min_payout,
            "stratum": list(m.stratum),
            "password": m.password,
            "note": m.note,
            "ports": [],
        }
        for m in pool.modes
    ]
    fees = [m.get("fee") for m in modes if m.get("fee") is not None]
    schemes = []
    for m in modes:
        if m.get("scheme") and m.get("listed", True) and m["scheme"] not in schemes:
            schemes.append(m["scheme"])
    hashrate = state.get("hashrate") if state.get("ok") else None
    if state.get("problem"):
        status = state["problem"]
    elif api:
        status = "up"
    else:
        status = "none"
    return {
        "slug": pool.slug,
        "id": pool.id,
        "name": pool.display,
        "list_name": pool.name,
        "domain": pool.domain,
        "website": pool.website or pool.link,
        "country": pool.country,
        "country_code": country_code(pool.country),
        "flag": _flag(country_code(pool.country)),
        "logo": f"/logos/{pool.slug}.svg" if has_logo else None,
        "software": pool.software or None,
        "api": api,
        "status": status,
        "error": state.get("error") or None,
        "checked_at": state.get("checked_at"),
        "hashrate": _round(hashrate),
        "hashrate_share": round(hashrate / network_24h, 4) if hashrate and network_24h else None,
        "hashrate_24h": _round(reported_24h),
        "hashrate_from_blocks_24h": _round(own_work / DAY) if own_work else 0,
        "miners": state.get("miners") if state.get("ok") else None,
        "workers": state.get("workers") if state.get("ok") else None,
        "height": state.get("height"),
        "schemes": schemes,
        "solo_only": schemes == ["SOLO"],
        "fee_min": min(fees) if fees else None,
        "fee_max": max(fees) if fees else None,
        "account": pool.account,
        "blocks": blocks,
        "blocks_total": totals["n"],
        "mined_dmd": _round(totals["mined"], 2) if totals["mined"] is not None else None,
        "last_block": dict(last) if last else None,
        "first_block": dict(first) if first else None,
        "luck_24h": _luck(c, blocks["24h"], reported_24h, answered_24h, now - DAY, now),
        "effort": next(
            (
                m.get("effort")
                for m in modes
                if m.get("effort") is not None and m.get("scheme") != "SOLO"
            ),
            None,
        ),
        "spark": _spark(conn, pool.slug, now, api),
    }


def _others(conn: sqlite3.Connection, now: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT miner, count(*) AS n, sum(time > ?) AS day, sum(time > ?) AS week, max(height) AS "
        "last, max(time) AS last_time FROM blocks WHERE slug IS NULL AND time > ? GROUP BY miner "
        "ORDER BY n DESC LIMIT 20",
        (now - DAY, now - 7 * DAY, now - 30 * DAY),
    ).fetchall()
    return [
        {
            "name": _name(None, r["miner"], {}),
            "blocks": {"24h": r["day"], "7d": r["week"], "30d": r["n"]},
            "last_block": {"height": r["last"], "time": r["last_time"]},
        }
        for r in rows
    ]


def network(conn: sqlite3.Connection, c: Chain, now: int) -> dict[str, Any]:
    last = conn.execute("SELECT * FROM blocks ORDER BY height DESC LIMIT 1").fetchone()
    day = conn.execute(
        "SELECT count(*) AS n, min(time) AS first FROM blocks WHERE time > ?", (now - DAY,)
    ).fetchone()
    height = last["height"] if last else 0
    cycle = height % chain.SUBSIDY_CYCLE_BLOCKS
    next_halving = height - cycle + (cycle // chain.HALVING_BLOCKS + 1) * chain.HALVING_BLOCKS
    return {
        "height": height,
        "last_block": {
            "height": height,
            "time": last["time"],
            "hash": last["hash"],
            "miner": last["miner"],
            "slug": last["slug"],
        }
        if last
        else None,
        "difficulty": last["difficulty"] if last else None,
        "hashrate_1h": _round(c.hashrate(now, HOUR)),
        "hashrate_24h": _round(c.hashrate(now, DAY)),
        "blocks_24h": day["n"],
        "block_seconds_24h": round(DAY / day["n"], 1) if day["n"] else None,
        "target_block_seconds": chain.BLOCK_SECONDS,
        "reward_dmd": chain.subsidy(height + 1),
        "next_halving_height": next_halving,
        "blocks_known": len(c.heights),
    }


def distribution(conn: sqlite3.Connection, pools: dict[str, Pool], now: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    windows = {
        "24h": DAY,
        "7d": 7 * DAY,
        "30d": 30 * DAY,
        "1y": 365 * DAY,
        "all": None,
        "1000": None,
    }
    for name, span in windows.items():
        if name == "1000":
            rows = _blocks_by(conn, 0, 1000)
        else:
            rows = _blocks_by(conn, now - span if span else -1)
        total = sum(r["n"] for r in rows)
        items = [
            {
                "key": r["who"],
                "slug": r["slug"],
                "name": _name(r["slug"], r["miner"], pools),
                "listed": r["slug"] is not None,
                "blocks": r["n"],
                "share": round(r["n"] / total, 4) if total else 0,
            }
            for r in rows
        ]
        out[name] = {
            "blocks": total,
            "miners": items[:40],
            "nakamoto": nakamoto([r["n"] for r in rows]),
            "top_share": items[0]["share"] if items else None,
        }
    return out


def _buckets(start: int, end: int, step: int) -> list[int]:
    """The steps from the first one that starts within the range, to the current one."""
    first = start - start % step
    if first < start:
        first += step
    return list(range(first, end - end % step + 1, step)) or [end - end % step]


def _hashrate_from_blocks(
    conn: sqlite3.Connection,
    pools: dict[str, Pool],
    times: list[int],
    step: int,
    window: int,
    now: int,
) -> list[dict[str, Any]]:
    """Each pool's hashrate from the blocks it found, as the mempool explorer works it out: the
    work of its blocks (difficulty × 2^32 each) over the window, divided by the window. It covers
    every block since block 1, the pools without an API too, and together they make the
    network's. The biggest pools each, the others (and the miners not in the list) together."""
    found: dict[str, tuple[list[int], list[float]]] = {}
    names: dict[str, str] = {}
    for r in conn.execute(
        "SELECT coalesce(slug, '~' || miner) AS who, slug, miner, time, difficulty FROM blocks "
        "WHERE time > ? AND time <= ? ORDER BY time",
        (times[0] - window, now),
    ):
        when, works = found.setdefault(r["who"], ([], []))
        when.append(r["time"])
        works.append(r["difficulty"] * WORK)
        names[r["who"]] = _name(r["slug"], r["miner"], pools)
    in_range = {k: sum(w for t, w in zip(*found[k], strict=True) if t > times[0]) for k in found}
    ranked = sorted((k for k in found if in_range[k] > 0), key=lambda k: -in_range[k])
    shown = [k for k in ranked if not k.startswith("~")][:TOP_SERIES]
    rest = [k for k in found if k not in shown]

    def series(keys: list[str]) -> list[float | None]:
        prefix: list[tuple[list[int], list[float]]] = []
        for k in keys:
            when, works = found[k]
            sums = [0.0]
            for w in works:
                sums.append(sums[-1] + w)
            prefix.append((when, sums))
        out: list[float | None] = []
        for t in times:
            end = min(t + step, now)
            total = 0.0
            for when, sums in prefix:
                a, b = bisect.bisect_right(when, end - window), bisect.bisect_right(when, end)
                total += sums[b] - sums[a]
            out.append(_round(total / window))
        return out

    out = [{"key": k, "slug": k, "name": names[k], "values": series([k])} for k in shown]
    if rest and any(in_range.get(k) for k in rest):
        out.append({"key": "others", "slug": None, "name": "Other miners", "values": series(rest)})
    return out


def chart(
    conn: sqlite3.Connection,
    c: Chain,
    pools: dict[str, Pool],
    name: str,
    now: int,
    api_slugs: list[str],
) -> dict[str, Any]:
    span, step, window, block_step = RANGES[name]
    first_time = c.sorted_times[0] if c.sorted_times else now
    # (Everything: from the step the first block is in.)
    start = now - span if span else first_time - first_time % max(step, block_step)
    times = _buckets(start, now, step)
    # The pools' own hashrate (their APIs): minute figures for 24 hours, hourly ones beyond.
    series: dict[str, dict[int, float]] = {s: {} for s in api_slugs}
    if step < HOUR:
        rows = conn.execute(
            "SELECT slug, t - t % ? AS b, avg(hashrate) AS v FROM samples WHERE ok AND t >= ? "
            "GROUP BY slug, b",
            (step, times[0]),
        )
    else:
        done = int(db.get(conn, "hourly_done", 0))
        rows = list(
            conn.execute(
                "SELECT slug, t - t % ? AS b, avg(hashrate) AS v FROM hourly WHERE t >= ? AND "
                "hashrate IS NOT NULL GROUP BY slug, b",
                (step, times[0]),
            )
        ) + list(
            conn.execute(
                "SELECT slug, t - t % ? AS b, avg(hashrate) AS v FROM samples WHERE ok AND t >= ? "
                "GROUP BY slug, b",
                (step, max(done, times[0])),
            )
        )
    for r in rows:
        if r["slug"] in series and r["v"] is not None:
            series[r["slug"]][r["b"]] = r["v"]
    hashrate = {
        "step": step,
        "times": times,
        "network": [_round(c.hashrate(min(t + step, now), max(window, step))) for t in times],
        "pools": [
            {
                "slug": s,
                "name": pools[s].display,
                "values": [_round(series[s].get(t)) if t in series[s] else None for t in times],
            }
            for s in api_slugs
            if series[s]
        ],
        "window": window,
        "from_blocks": _hashrate_from_blocks(conn, pools, times, step, max(window, step), now),
    }
    # The blocks each found, a bar per step.
    btimes = _buckets(start, now, block_step)
    counts: dict[str, dict[int, int]] = {}
    names: dict[str, str] = {}
    total_by: dict[str, int] = {}
    for r in conn.execute(
        "SELECT coalesce(slug, '~' || miner) AS who, slug, miner, time - time % ? AS b, "
        "count(*) AS n FROM blocks WHERE time >= ? GROUP BY who, b",
        (block_step, btimes[0]),
    ):
        counts.setdefault(r["who"], {})[r["b"]] = r["n"]
        names[r["who"]] = _name(r["slug"], r["miner"], pools)
        total_by[r["who"]] = total_by.get(r["who"], 0) + r["n"]
    ranked = sorted(total_by, key=lambda k: -total_by[k])
    shown = [k for k in ranked if not k.startswith("~")][:TOP_SERIES]
    rest = [k for k in ranked if k not in shown]
    blocks_series = [
        {"key": k, "slug": k, "name": names[k], "values": [counts[k].get(t, 0) for t in btimes]}
        for k in shown
    ]
    if rest:
        blocks_series.append(
            {
                "key": "others",
                "slug": None,
                "name": "Other miners",
                "values": [sum(counts[k].get(t, 0) for k in rest) for t in btimes],
            }
        )
    return {
        "range": name,
        "updated": now,
        "hashrate": hashrate,
        "blocks": {"step": block_step, "times": btimes, "series": blocks_series},
    }


def pool_detail(
    conn: sqlite3.Connection,
    pool: Pool,
    entry: dict[str, Any],
    c: Chain,
    now: int,
    explorer: str,
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM pool_state WHERE slug = ?", (pool.slug,)).fetchone()
    state = json.loads(row["data"]) if row else {}
    modes = []
    for m in state.get("modes") or [
        {
            "label": x.label,
            "scheme": x.scheme or None,
            "fee": x.fee,
            "min_payout": x.min_payout,
            "stratum": list(x.stratum),
            "password": x.password,
            "note": x.note,
            "ports": [],
            "listed": True,
        }
        for x in pool.modes
    ]:
        modes.append({**m, "endpoints": stratum_urls(pool, m)})
    statuses = {
        (r["height"], r["hash"]): dict(r)
        for r in conn.execute(
            "SELECT height, hash, status, effort, reward, mode FROM pool_blocks WHERE slug = ?",
            (pool.slug,),
        )
    }
    found = []
    for r in conn.execute(
        "SELECT height, hash, time, reward, tx FROM blocks WHERE slug = ? ORDER BY height DESC "
        "LIMIT 100",
        (pool.slug,),
    ):
        extra = statuses.get((r["height"], r["hash"]), {})
        found.append(
            {
                **dict(r),
                "status": extra.get("status"),
                "effort": extra.get("effort"),
                "mode": extra.get("mode"),
            }
        )
    on_chain = {(f["height"], f["hash"]) for f in found}
    orphaned = [
        {"height": r["height"], "hash": r["hash"], "time": r["created"], "mode": r["mode"]}
        for r in conn.execute(
            "SELECT * FROM pool_blocks WHERE slug = ? AND status = 'orphaned' AND created > ? "
            "ORDER BY height DESC LIMIT 20",
            (pool.slug, now - 30 * DAY),
        )
        if (r["height"], r["hash"]) not in on_chain
    ]
    efforts = [
        r["effort"]
        for r in conn.execute(
            "SELECT effort FROM pool_blocks WHERE slug = ? AND effort IS NOT NULL AND created > ?",
            (pool.slug, now - 30 * DAY),
        )
    ]
    reported_7d, answered_7d, _ = _reported(conn, pool.slug, now - 7 * DAY)
    week = entry["blocks"]["7d"]
    charts = {}
    for name in ("24h", "7d", "30d", "1y"):
        span, step, window, block_step = RANGES[name]
        times = _buckets(now - span, now, step)
        source = "samples" if step < HOUR else "hourly"
        values: dict[int, float] = {}
        query = (
            f"SELECT t - t % ? AS b, avg(hashrate) AS v FROM {source} WHERE slug = ? AND t >= ? "
            + ("AND ok " if source == "samples" else "AND hashrate IS NOT NULL ")
            + "GROUP BY b"
        )
        for r in conn.execute(query, (step, pool.slug, times[0])):
            values[r["b"]] = r["v"]
        if source == "hourly":
            done = int(db.get(conn, "hourly_done", 0))
            for r in conn.execute(
                "SELECT t - t % ? AS b, avg(hashrate) AS v FROM samples WHERE slug = ? AND ok AND "
                "t >= ? GROUP BY b",
                (step, pool.slug, max(done, times[0])),
            ):
                values.setdefault(r["b"], r["v"])
        own: list[tuple[int, float]] = [
            (r["time"], r["difficulty"] * WORK)
            for r in conn.execute(
                "SELECT time, difficulty FROM blocks WHERE slug = ? AND time >= ? ORDER BY time",
                (pool.slug, times[0] - max(window, step) * 3),
            )
        ]
        own_times = [t for t, _ in own]
        own_prefix = [0.0]
        for _, w in own:
            own_prefix.append(own_prefix[-1] + w)

        def from_blocks(
            end: int, width: int, ot: list[int] = own_times, op: list[float] = own_prefix
        ) -> float:
            a, b = bisect.bisect_right(ot, end - width), bisect.bisect_right(ot, end)
            return (op[b] - op[a]) / width

        win = max(window, step) * (3 if name == "24h" else 1)
        bt = _buckets(now - span, now, block_step)
        bcounts = {
            r["b"]: r["n"]
            for r in conn.execute(
                "SELECT time - time % ? AS b, count(*) AS n FROM blocks WHERE slug = ? AND "
                "time >= ? GROUP BY b",
                (block_step, pool.slug, bt[0]),
            )
        }
        charts[name] = {
            "step": step,
            "times": times,
            "reported": [_round(values.get(t)) if t in values else None for t in times],
            "from_blocks": [_round(from_blocks(min(t + step, now), win)) for t in times],
            "blocks": {"step": block_step, "times": bt, "values": [bcounts.get(t, 0) for t in bt]},
            "window": win,
        }
    difficulty = c.work[-1] / WORK if c.work else None
    hashrate = entry["hashrate"]
    return {
        **entry,
        "updated": now,
        "link": pool.link,
        "addresses": list(pool.addresses),
        "tags": list(pool.tags),
        "username": pool.username or None,
        "notes": pool.notes or None,
        "hosts": list(pool.hosts),
        "modes": modes,
        "ok_at": row["ok_at"] if row else None,
        "fail_since": row["fail_since"] if row else None,
        "uptime_24h": _uptime(conn, pool.slug, now - DAY),
        "uptime_7d": _uptime(conn, pool.slug, now - 7 * DAY),
        "luck_7d": _luck(c, week, reported_7d, answered_7d, now - 7 * DAY, now),
        "effort_30d": round(sum(efforts) / len(efforts), 4) if efforts else None,
        "seconds_per_block": round(difficulty * WORK / hashrate)
        if difficulty and hashrate
        else None,
        "found": found,
        "orphaned": orphaned,
        "explorer": explorer,
        "charts": charts,
    }


def latest_blocks(conn: sqlite3.Connection, pools: dict[str, Pool], count: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT b.*, (SELECT time FROM blocks p WHERE p.height = b.height - 1) AS before "
        "FROM blocks b ORDER BY height DESC LIMIT ?",
        (count,),
    ).fetchall()
    statuses = {
        (r["height"], r["hash"]): r["status"]
        for r in conn.execute(
            "SELECT height, hash, status FROM pool_blocks WHERE height >= ?",
            (rows[-1]["height"] if rows else 0,),
        )
    }
    return [
        {
            "height": r["height"],
            "hash": r["hash"],
            "time": r["time"],
            "seconds": r["time"] - r["before"] if r["before"] is not None else None,
            "miner": _name(r["slug"], r["miner"], pools),
            "slug": r["slug"],
            "reward": r["reward"],
            "tx": r["tx"],
            "size": r["size"],
            "difficulty": r["difficulty"],
            "status": statuses.get((r["height"], r["hash"])),
        }
        for r in rows
    ]


def publish(
    conn: sqlite3.Connection,
    catalog: Catalog,
    folder: Path,
    now: int,
    explorer: str,
    slow_too: bool = False,
) -> None:
    api = folder / "api"
    c = Chain.load(conn)
    pools = catalog.by_slug()
    net = network(conn, c, now)
    entries = []
    for pool in catalog.pools:
        entries.append(
            pool_entry(conn, pool, c, now, net["hashrate_24h"], pool.slug in catalog.logos)
        )
    dist = distribution(conn, pools, now)
    # The pools that mine (a block in 30 days, or an API that answers), then the others.
    entries.sort(
        key=lambda e: (
            -(e["blocks"]["30d"] > 0 or e["status"] in ("up", "behind")),
            -(e["hashrate"] or 0),
            -e["blocks"]["24h"],
            -e["blocks"]["30d"],
            e["name"].lower(),
        )
    )
    # Each pool's colour on the site: the pools that mine, the DebitMyData pool first, then by their
    # number in the list (a pool keeps its colour as the others' hashrate changes); 7 at most.
    active = sorted(
        (e for e in entries if e["blocks"]["30d"] or e["status"] in ("up", "behind")),
        key=lambda e: (e["slug"] != "official", e["id"]),
    )
    colors = {e["slug"]: n for n, e in enumerate(active[:COLORS])}
    for e in entries:
        e["color"] = colors.get(e["slug"])
    reported = sum(e["hashrate"] or 0 for e in entries)
    day = dist["24h"]
    listed_24h = sum(m["blocks"] for m in day["miners"] if m["listed"])
    summary = {
        "updated": now,
        "version": __version__,
        "network": net,
        "pools": entries,
        "others": _others(conn, now),
        "totals": {
            "reported_hashrate": _round(reported) if reported else None,
            "reported_share": round(reported / net["hashrate_24h"], 4)
            if reported and net["hashrate_24h"]
            else None,
            "pools_active_24h": sum(1 for e in entries if e["blocks"]["24h"]),
            "pools_answering": sum(1 for e in entries if e["status"] == "up"),
            "listed_blocks_24h": listed_24h,
            "other_blocks_24h": day["blocks"] - listed_24h,
            "nakamoto_24h": day["nakamoto"],
            "nakamoto_7d": dist["7d"]["nakamoto"],
            "top_24h": day["miners"][0] if day["miners"] else None,
        },
        "chain_read_at": db.get(conn, "chain_read_at"),
        "polled_at": db.get(conn, "polled_at"),
        "pools_list": catalog.digest or None,
    }
    _write(api / "summary.json", summary)
    _write(api / "blocks.json", {"updated": now, "blocks": latest_blocks(conn, pools)})
    _write(api / "distribution.json", {"updated": now, **dist})
    api_slugs = [e["slug"] for e in entries if e["api"]]
    for name in RANGES:
        path = api / f"chart-{name}.json"
        every = SLOW_RANGES.get(name)
        if every and not slow_too and path.exists() and now - path.stat().st_mtime < every:
            continue
        _write(path, chart(conn, c, pools, name, now, api_slugs))
    for entry in entries:
        pool = pools[entry["slug"]]
        path = api / "pools" / f"{pool.slug}.json"
        quiet = not entry["api"] and not entry["blocks"]["30d"]  # (its page changes slowly)
        if quiet and not slow_too and path.exists():
            continue
        _write(path, pool_detail(conn, pool, entry, c, now, explorer))
    keep = {f"{e['slug']}.json" for e in entries}
    for old in (api / "pools").glob("*.json"):
        if old.name not in keep:
            old.unlink(missing_ok=True)
