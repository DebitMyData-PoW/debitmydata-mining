"""dmd-mining: the DMD Mining server's commands.

  dmd-mining run           the service (dmd-mining.service): everything below, on its own clock
  dmd-mining publish       writes the site's files now
  dmd-mining pools         reads DebitMyData's pool list and logos from GitHub now
  dmd-mining status        what the server knows: blocks, pools, devices
  dmd-mining push-keys     shows the notifications' public key (makes the key if there is none)

The service, every 20 seconds: the new blocks from DMD Stats; every minute: each pool's API; then
the events become notices, and the site's files are written again. Every hour: the pool list.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sqlite3
import sys
import time
from typing import Any

from dmdmining import __version__, api, catalog, chain, db, fetch, notify, poller, publish, push
from dmdmining.config import Settings

log = logging.getLogger("dmdmining")


class Service:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.conn = db.connect(settings.database)
        self.catalog = catalog.load(settings.catalog_dir)
        self.keys = push.load_keys(settings.push_key_file)
        self.notifier = (
            notify.Notifier(self.conn, self.keys, settings.push_subject) if self.keys else None
        )
        self.next = {
            "catalog": 0.0,
            "reload": 0.0,
            "chain": 0.0,
            "poll": 0.0,
            "aggregate": 0.0,
            "publish": 0.0,
            "slow": 0.0,
        }
        self.stopping = False
        self.changed = False

    def step(self, name: str, every: float, clock: float, work: Any) -> bool:
        if clock < self.next[name]:
            return False
        self.next[name] = clock + every
        try:
            work()
            return True
        except fetch.FetchError as exc:
            log.warning("%s: %s", name, exc)
        except (sqlite3.Error, OSError, ValueError) as exc:
            log.exception("%s failed: %s", name, exc)
        return False

    def refresh_catalog(self) -> None:
        s = self.settings
        before = self.catalog.digest
        self.catalog = catalog.refresh(s.pools_url, s.logos_url, s.catalog_dir)
        publish_logos(s, self.catalog)
        if self.catalog.digest != before:
            log.info("pool list: %d pools (%s)", len(self.catalog.pools), self.catalog.digest)
            self.next["chain"] = 0
            db.put(self.conn, "chain_full_sync", 0)  # names old blocks again

    def reload_catalog(self) -> None:
        """The list as `dmd-mining pools` may have just read it from GitHub."""
        fresh = catalog.load(self.settings.catalog_dir)
        if fresh.pools and (fresh.digest, fresh.logos) != (self.catalog.digest, self.catalog.logos):
            before = self.catalog.digest
            self.catalog = fresh
            publish_logos(self.settings, fresh)
            if fresh.digest != before:
                log.info("pool list: %d pools (%s)", len(fresh.pools), fresh.digest)
                db.put(self.conn, "chain_full_sync", 0)
            self.next["publish"] = 0

    def round(self) -> None:
        clock = time.monotonic()
        now = int(time.time())
        s = self.settings
        self.changed = False
        self.step("catalog", s.catalog_seconds, clock, self.refresh_catalog)
        self.step("reload", 30, clock, self.reload_catalog)
        self.step("chain", s.chain_seconds, clock, lambda: self._chain(now))
        if self.step(
            "poll", s.poll_seconds, clock, lambda: poller.poll(self.conn, self.catalog, now)
        ):
            self.changed = True
        changed = self.changed
        if changed:
            poller.majority(self.conn, now)
        self.step("aggregate", 300, clock, lambda: poller.aggregate(self.conn, now))
        if self.notifier is not None:
            try:
                self.notifier.run_once(self.catalog, now)
            except (sqlite3.Error, OSError) as exc:
                log.exception("notifications: %s", exc)
        if changed or clock >= self.next["publish"]:
            self.next["publish"] = clock + 60
            slow = clock >= self.next["slow"]
            if slow:
                self.next["slow"] = clock + 600
            try:
                publish.publish(
                    self.conn, self.catalog, s.public_dir, now, s.explorer_url, slow_too=slow
                )
            except (sqlite3.Error, OSError, ValueError) as exc:
                log.exception("publish: %s", exc)

    def _chain(self, now: int) -> None:
        new = chain.follow(self.conn, self.settings.stats_url, self.catalog, now)
        if new:
            self.changed = True

    def run(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stopping", True))
        server = None
        if self.keys is not None:
            server = api.serve(
                api.PushApi(
                    str(self.settings.database),
                    self.keys,
                    self.settings.site_url,
                    self.settings.push_max_devices,
                ),
                self.settings.push_listen,
            )
        else:
            log.warning(
                "no notifications key (%s): dmd-mining push-keys", self.settings.push_key_file
            )
        log.info("DMD Mining %s: %d pools known", __version__, len(self.catalog.pools))
        while not self.stopping:
            started = time.monotonic()
            self.round()
            time.sleep(max(0.5, 2 - (time.monotonic() - started)))
        if server is not None:
            server.shutdown()


def publish_logos(settings: Settings, cat: catalog.Catalog) -> None:
    """The logos the site shows (/logos/<slug>.svg), from the ones read from GitHub."""
    out = settings.public_dir / "logos"
    out.mkdir(parents=True, exist_ok=True)
    source = settings.catalog_dir / "logos"
    keep = set()
    for path in source.glob("*.svg"):
        data = path.read_bytes()
        target = out / path.name
        keep.add(path.name)
        if not target.exists() or target.read_bytes() != data:
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.chmod(0o644)
            tmp.replace(target)
    for path in out.glob("*.svg"):
        if path.name not in keep:
            path.unlink(missing_ok=True)


def cmd_status(settings: Settings) -> int:
    conn = db.connect(settings.database)
    blocks = conn.execute(
        "SELECT count(*) AS n, max(height) AS h, max(time) AS t FROM blocks"
    ).fetchone()
    print(f"Blocks: {blocks['n']} (last {blocks['h']}, {_ago(blocks['t'])})")
    print(f"Chain read from DMD Stats: {_ago(db.get(conn, 'chain_read_at'))}")
    print(f"Pools' APIs read: {_ago(db.get(conn, 'polled_at'))}")
    cat = catalog.load(settings.catalog_dir)
    print(f"Pool list: {len(cat.pools)} pools ({cat.digest or 'not read yet'})")
    for row in conn.execute("SELECT * FROM pool_state ORDER BY slug"):
        state = json.loads(row["data"])
        what = "no API" if not state.get("api") else (state.get("problem") or "answering")
        rate = state.get("hashrate")
        print(f"  {row['slug']:<16} {what:<10} {_rate(rate):>12}  {state.get('error') or ''}")
    devices = conn.execute("SELECT count(*) AS n FROM devices").fetchone()["n"]
    print(f"Devices with notifications on: {devices}")
    return 0


def _ago(t: Any) -> str:
    if not t:
        return "never"
    s = int(time.time()) - int(t)
    return f"{s} s ago" if s < 120 else f"{s // 60} min ago" if s < 7200 else f"{s // 3600} h ago"


def _rate(v: Any) -> str:
    if not v:
        return "–"
    for unit, size in (("PH/s", 1e15), ("TH/s", 1e12), ("GH/s", 1e9), ("MH/s", 1e6)):
        if v >= size:
            return f"{v / size:.2f} {unit}"
    return f"{v:.0f} H/s"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dmd-mining", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["run", "publish", "pools", "status", "push-keys"])
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout
    )
    settings = Settings.from_env()
    if args.command == "run":
        Service(settings).run()
        return 0
    if args.command == "publish":
        conn = db.connect(settings.database)
        cat = catalog.load(settings.catalog_dir)
        publish_logos(settings, cat)
        publish.publish(
            conn, cat, settings.public_dir, int(time.time()), settings.explorer_url, slow_too=True
        )
        print(f"Written in {settings.public_dir}/api")
        return 0
    if args.command == "pools":
        cat = catalog.refresh(settings.pools_url, settings.logos_url, settings.catalog_dir)
        publish_logos(settings, cat)
        print(f"{len(cat.pools)} pools, {len(cat.logos)} logos ({cat.digest})")
        for p in cat.pools:
            api_text = f"{p.software} API" if p.api else "no API"
            print(f"  {p.id:>3} {p.slug:<16} {p.display:<20} {api_text}")
        return 0
    if args.command == "status":
        return cmd_status(settings)
    if args.command == "push-keys":
        keys, new = push.make_keys(settings.push_key_file)
        print(("New key made. " if new else "") + f"Public key: {keys.public}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
