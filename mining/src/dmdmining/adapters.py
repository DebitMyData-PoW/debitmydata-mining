"""Each pool's own figures, from its API, once a minute. Two kinds are read:

  MiningCore   {api}/pools: each of its pools (a "mode" here: PPLNS, solo...) with its hashrate,
               miners, fee, payout scheme, minimum payment, ports and their difficulty, its node's
               height, its effort; {api}/pools/<id>/blocks (every 5 minutes): its last blocks
               with their status (pending, confirmed, orphaned) and effort
  YIIMP        {api}/currencies: the coin's hashrate, workers, height and last block;
               {api}/status: the algorithm's fee and port

A pool without an API (or another kind) shows its blocks from the chain, and what pools-info.json
says about it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dmdmining import fetch
from dmdmining.catalog import SCHEMES, Mode, Pool

log = logging.getLogger(__name__)

BLOCKS_EVERY = 300  # seconds between two reads of a MiningCore pool's blocks
DMD_NAMES = ("dmd", "debitmydata")


def _num(value: Any, low: float = 0, high: float = 1e30) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, int | float) or value != value:
        return None
    return float(value) if low <= value <= high else None


def _int(value: Any, low: int = 0, high: int = 10**12) -> int | None:
    n = _num(value, low, high)
    return int(n) if n is not None else None


def _time(value: Any) -> int | None:
    """A MiningCore time ("2026-11-22T15:41:54.054351", UTC, with or without a zone)."""
    if not isinstance(value, str) or not value:
        return None
    text = re.sub(r"(\.\d{6})\d+", r"\1", value.strip().replace("Z", "+00:00"))
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return int(when.timestamp())


@dataclass
class ModeFigures:
    label: str
    api_id: str = ""
    listed: bool = True  # the API still has it
    scheme: str = ""
    fee: float | None = None
    min_payout: float | None = None
    ports: list[dict[str, Any]] = field(default_factory=list)
    stratum: list[str] = field(default_factory=list)
    password: str = ""
    note: str = ""
    hashrate: float | None = None
    miners: int | None = None
    workers: int | None = None
    height: int | None = None
    network_hashrate: float | None = None
    total_blocks: int | None = None
    total_paid: float | None = None
    effort: float | None = None
    last_block: int | None = None

    def public(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Figures:
    ok: bool
    error: str = ""
    modes: list[ModeFigures] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)  # from the API (MiningCore)

    def total(self, name: str) -> float | None:
        values = [getattr(m, name) for m in self.modes if getattr(m, name) is not None]
        return sum(values) if values else None

    @property
    def height(self) -> int | None:
        values = [m.height for m in self.modes if m.height is not None]
        return max(values) if values else None


def _from_info(mode: Mode) -> ModeFigures:
    return ModeFigures(
        label=mode.label,
        api_id=mode.api_id,
        scheme=mode.scheme,
        fee=mode.fee,
        min_payout=mode.min_payout,
        stratum=list(mode.stratum),
        password=mode.password,
        note=mode.note,
    )


def _ports(raw: Any) -> list[dict[str, Any]]:
    out = []
    for port, conf in (raw or {}).items() if isinstance(raw, dict) else []:
        number = _int(port, 1, 65535)
        if number is None or not isinstance(conf, dict):
            continue
        var = conf.get("varDiff") if isinstance(conf.get("varDiff"), dict) else None
        out.append(
            {
                "port": number,
                "name": conf.get("name")[:60] if isinstance(conf.get("name"), str) else None,
                "difficulty": _num(conf.get("difficulty")),
                "vardiff": {"min": _num(var.get("minDiff")), "max": _num(var.get("maxDiff"))}
                if var
                else None,
                "tls": conf.get("tls") is True,
            }
        )
    out.sort(key=lambda p: p["port"])
    return out[:20]


def _is_dmd(entry: dict[str, Any]) -> bool:
    coin = entry.get("coin") if isinstance(entry.get("coin"), dict) else {}
    names = [str(coin.get(k) or "").lower() for k in ("symbol", "name", "type", "canonicalName")]
    return any(n in DMD_NAMES for n in names)


def miningcore(pool: Pool, now: int, blocks_due: bool) -> Figures:
    data = fetch.get_json(f"{pool.api}/pools")
    entries = data.get("pools") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise fetch.FetchError("no pools in the answer")
    by_id = {str(e.get("id")): e for e in entries if isinstance(e, dict)}
    modes = [_from_info(m) for m in pool.modes if m.api_id] or [
        ModeFigures(label="", api_id=key) for key, e in by_id.items() if _is_dmd(e)
    ]
    figures = Figures(ok=True)
    for mode in modes:
        entry = by_id.get(mode.api_id)
        if entry is None:
            mode.listed = False
            figures.modes.append(mode)
            continue
        pay = (
            entry.get("paymentProcessing")
            if isinstance(entry.get("paymentProcessing"), dict)
            else {}
        )
        scheme = str(pay.get("payoutScheme") or "").upper()
        stats = entry.get("poolStats") if isinstance(entry.get("poolStats"), dict) else {}
        network = entry.get("networkStats") if isinstance(entry.get("networkStats"), dict) else {}
        mode.scheme = scheme if scheme in SCHEMES else mode.scheme
        mode.label = mode.label or (mode.scheme.title() if mode.scheme else mode.api_id)
        fee = _num(entry.get("poolFeePercent"), 0, 100)
        mode.fee = fee if fee is not None else mode.fee
        minimum = _num(pay.get("minimumPayment"), 0, 1e9)
        mode.min_payout = minimum if minimum is not None else mode.min_payout
        mode.ports = _ports(entry.get("ports"))
        mode.hashrate = _num(stats.get("poolHashrate"))
        mode.miners = _int(stats.get("connectedMiners"))
        mode.height = _int(network.get("blockHeight"))
        mode.network_hashrate = _num(network.get("networkHashrate"))
        mode.total_blocks = _int(entry.get("totalBlocks"))
        mode.total_paid = _num(entry.get("totalPaid"))
        mode.effort = _num(entry.get("poolEffort"), 0, 1e6)
        mode.last_block = _time(entry.get("lastPoolBlockTime"))
        figures.modes.append(mode)
        if blocks_due:
            try:
                figures.blocks += _miningcore_blocks(pool, mode)
            except fetch.FetchError as exc:
                log.info("%s: blocks of %s not read (%s)", pool.slug, mode.api_id, exc)
    if not any(m.listed for m in figures.modes):
        figures.ok = False
        figures.error = "its API no longer lists a DMD pool"
    return figures


def _miningcore_blocks(pool: Pool, mode: ModeFigures) -> list[dict[str, Any]]:
    rows = fetch.get_json(f"{pool.api}/pools/{mode.api_id}/blocks?page=0&pageSize=50")
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        height, block_hash = _int(row.get("blockHeight")), row.get("hash")
        status = str(row.get("status") or "").lower()
        if (
            height is None
            or not isinstance(block_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", block_hash)
        ):
            continue
        out.append(
            {
                "mode": mode.label,
                "height": height,
                "hash": block_hash,
                "status": status if status in ("pending", "confirmed", "orphaned") else "pending",
                "effort": _num(row.get("effort"), 0, 1e6),
                "reward": _num(row.get("reward"), 0, 1e9),
                "created": _time(row.get("created")),
                "miner": str(row.get("miner") or "")[:100] or None,
            }
        )
    return out


def yiimp(pool: Pool, now: int, blocks_due: bool) -> Figures:
    data = fetch.get_json(f"{pool.api}/currencies")
    coin = pool.api_coin or "DMD"
    entry = data.get(coin) if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        raise fetch.FetchError(f"{coin} is not in its API")
    modes = [_from_info(m) for m in pool.modes] or [ModeFigures(label="Pool")]
    algo, fee, port = str(entry.get("algo") or ""), None, _int(entry.get("port"), 1, 65535)
    try:
        status = fetch.get_json(f"{pool.api}/status")
        algo_entry = status.get(algo) if isinstance(status, dict) else None
        if isinstance(algo_entry, dict):
            fee = _num(algo_entry.get("fees"), 0, 100)
    except fetch.FetchError:
        pass
    last = _int(entry.get("lastblock"))
    since = _int(entry.get("timesincelast"))
    first = modes[0]
    first.hashrate = _num(entry.get("hashrate"))
    first.workers = _int(entry.get("workers"))
    first.height = _int(entry.get("height"))
    first.network_hashrate = _num(entry.get("network_hashrate"))
    first.last_block = now - since if last and since is not None and since < 10**9 else None
    for mode in modes:
        if mode.fee is None and fee is not None and mode.scheme != "SOLO":
            mode.fee = fee
        if not mode.stratum and port and pool.domain:
            mode.stratum = [f"{pool.domain}:{port}"]
    return Figures(ok=True, modes=modes)


def static(pool: Pool) -> Figures:
    """No API: what pools-info.json says."""
    return Figures(ok=False, error="no API", modes=[_from_info(m) for m in pool.modes])


def read(pool: Pool, now: int, blocks_due: bool) -> Figures:
    if not pool.api:
        return static(pool)
    reader = {"MiningCore": miningcore, "YIIMP": yiimp}.get(pool.software)
    if reader is None:
        return static(pool)
    try:
        return reader(pool, now, blocks_due)
    except fetch.FetchError as exc:
        figures = static(pool)
        figures.error = str(exc)[:200]
        return figures
