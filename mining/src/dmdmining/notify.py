"""The notifications each device chose, sent as web push (push.py) within seconds of the events.

A device chooses:
  pools      up to 20 pools, by slug: a notice for each block each finds
  problems   for those pools, a notice when one stops answering or its node falls behind, and
             when it's back (on by default)
  majority   a notice when one miner finds more than half of the last 144 blocks, and when it's
             back under 45% (off by default)

Several blocks of one pool since the last round make one notice ("CyberPool found 3 blocks"); a
newer notice of the same kind replaces one the device hasn't shown yet (its tag).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlsplit

from dmdmining import push
from dmdmining.catalog import Catalog

log = logging.getLogger(__name__)

MAX_POOLS = 20
MAX_FAILURES = 100
INBOX_ITEMS = 40
INBOX_SECONDS = 3 * 86400
SENDERS = 8
DEFAULT_PREFS: dict[str, Any] = {"pools": [], "problems": True, "majority": False}
SLUG = re.compile(r"^[a-z0-9]{1,40}$")


def clean_prefs(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("The choices must be a JSON object.")
    pools = raw.get("pools", [])
    if not isinstance(pools, list) or not all(isinstance(p, str) and SLUG.match(p) for p in pools):
        raise ValueError("The pools must be a list of pool names.")
    unique = list(dict.fromkeys(pools))
    if len(unique) > MAX_POOLS:
        raise ValueError(f"You can follow {MAX_POOLS} pools at most.")
    return {
        "pools": unique,
        "problems": raw.get("problems", True) is not False,
        "majority": raw.get("majority", False) is True,
    }


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


def latest_event(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT coalesce(max(id), 0) AS id FROM events").fetchone()
    return int(row["id"])


def inbox(sent: list[dict[str, Any]], now: int) -> list[dict[str, Any]]:
    return [i for i in sent if i.get("time", 0) >= now - INBOX_SECONDS][-INBOX_ITEMS:]


def _height(h: int) -> str:
    return f"{h:,}"


def _notice(title: str, body: str, url: str, tag: str) -> dict[str, Any]:
    return {"title": title[:120], "body": body[:400], "url": url, "tag": tag[:32]}


def collect(
    device: sqlite3.Row, events: list[sqlite3.Row], names: dict[str, str]
) -> tuple[list[dict[str, Any]], int]:
    """The notices for this device from the events after its cursor, and its new cursor."""
    prefs = {**DEFAULT_PREFS, **json.loads(device["prefs"])}
    followed = set(prefs["pools"])
    cursor = int(device["cursor"])
    blocks: dict[str, list[dict[str, Any]]] = {}
    out: list[dict[str, Any]] = []
    for event in events:
        if event["id"] <= cursor:
            continue
        cursor = event["id"]
        data = json.loads(event["data"])
        slug = event["slug"]
        name = names.get(slug or "", data.get("miner") or slug or "A pool")
        url = f"/pool/{slug}" if slug else "/"
        if event["kind"] == "block" and slug in followed:
            blocks.setdefault(slug, []).append(data)
        elif event["kind"] == "pool_down" and prefs["problems"] and slug in followed:
            if data.get("reason") == "behind":
                body = (
                    f"Its node is at block {_height(data['height'])}, the chain at "
                    f"{_height(data['tip'])}: its miners may be working on old blocks."
                    if data.get("height") and data.get("tip")
                    else "Its node is behind the chain: its miners may be working on old blocks."
                )
                out.append(_notice(f"{name}'s node is behind", body, url, f"down-{slug}"))
            else:
                out.append(
                    _notice(
                        f"{name} isn't answering",
                        "Its API hasn't answered for 10 minutes: its stratum may be down too.",
                        url,
                        f"down-{slug}",
                    )
                )
        elif event["kind"] == "pool_up" and prefs["problems"] and slug in followed:
            body = (
                "Its node caught up with the chain."
                if data.get("was") == "behind"
                else "Its API answers again."
            )
            out.append(_notice(f"{name} is back", body, url, f"down-{slug}"))
        elif event["kind"] == "majority" and prefs["majority"]:
            who = names.get(slug or "") or _miner(data.get("miner") or data.get("who") or "")
            out.append(
                _notice(
                    "One miner finds most blocks",
                    f"{who} found {data['share']:.0%} of the last {data['of']} blocks (6 hours). "
                    "With more than half the hashrate, a miner could rewrite recent blocks.",
                    "/#decentralization",
                    "majority",
                )
            )
        elif event["kind"] == "majority_end" and prefs["majority"]:
            who = names.get(slug or "") or _miner(data.get("miner") or data.get("who") or "")
            out.append(
                _notice(
                    "Mining is spread out again",
                    f"{who} is back to {data['share']:.0%} of the last {data['of']} blocks.",
                    "/#decentralization",
                    "majority",
                )
            )
    for slug, found in blocks.items():
        heights = sorted(b["height"] for b in found)
        name = names.get(slug, slug)
        if len(heights) == 1:
            title, body = f"{name} found a block", f"Block {_height(heights[0])}."
        else:
            title = f"{name} found {len(heights)} blocks"
            body = f"Blocks {_height(heights[0])} to {_height(heights[-1])}."
        out.insert(0, _notice(title, body, f"/pool/{slug}", f"block-{slug}"))
    return out, cursor


def _miner(name: str) -> str:
    return "The DebitMyData pool" if name == "the DebitMyData pool" else (name or "One miner")


class Notifier:
    def __init__(self, conn: sqlite3.Connection, keys: push.Keys, subject: str) -> None:
        self.conn, self.keys, self.subject = conn, keys, subject
        self.threads = ThreadPoolExecutor(max_workers=SENDERS, thread_name_prefix="push")

    def _send(self, device: sqlite3.Row, messages: list[dict[str, Any]]) -> tuple[str, str]:
        answer = ""
        target = {
            "endpoint": device["endpoint"],
            "p256dh": device["p256dh"],
            "auth": device["auth"],
        }
        for message in messages:
            code, text = push.deliver(self.keys, self.subject, target, message)
            answer = f"{code} {text}".strip()
            if code in (404, 410):
                return "gone", answer
            if not 200 <= code < 300:
                return "failed", answer
        return "ok", answer

    def run_once(self, catalog: Catalog, now: int) -> int:
        devices = self.conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
        if not devices:
            return 0
        start = min(int(d["cursor"]) for d in devices)
        events = self.conn.execute(
            "SELECT * FROM events WHERE id > ? ORDER BY id LIMIT 5000", (start,)
        ).fetchall()
        names = {p.slug: p.display for p in catalog.pools}
        work = []
        for device in devices:
            if not events and device["test_at"] is None:
                continue
            messages, cursor = collect(device, events, names)
            if device["test_at"] is not None:
                messages.insert(
                    0, _notice("Test notice", "Notifications work on this device.", "/", "test")
                )
            for n, m in enumerate(messages):
                m["id"], m["time"] = f"{now}-{device['id']}-{n}", now
            work.append((device, messages, cursor))
        results = list(
            self.threads.map(lambda w: self._send(w[0], w[1]) if w[1] else ("ok", ""), work)
        )
        sent = 0
        for (device, messages, cursor), (state, answer) in zip(work, results, strict=True):
            host = urlsplit(device["endpoint"]).hostname
            if state == "gone" or (state == "failed" and device["failures"] + 1 >= MAX_FAILURES):
                log.info("device %s (%s) removed: %s", device["id"], host, answer)
                self.conn.execute("DELETE FROM devices WHERE id = ?", (device["id"],))
                continue
            if state == "failed":
                if device["failures"] % 20 == 0:
                    log.info("device %s (%s) not reached: %s", device["id"], host, answer)
                self.conn.execute(
                    "UPDATE devices SET failures = failures + 1, test_at = NULL WHERE id = ?",
                    (device["id"],),
                )
                continue
            sent += len(messages)
            items = inbox(
                json.loads(device["sent"] or "[]")
                + [
                    {k: m[k] for k in ("id", "time", "title", "body", "url")}
                    for m in messages
                    if m.get("tag") != "test"
                ],
                now,
            )
            self.conn.execute(
                "UPDATE devices SET cursor = ?, sent = ?, failures = 0, test_at = NULL "
                "WHERE id = ?",
                (cursor, json.dumps(items, separators=(",", ":")), device["id"]),
            )
        if sent:
            log.info("%d notices sent", sent)
        return sent
