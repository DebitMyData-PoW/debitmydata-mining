"""A stand-in for the sites DMD Mining reads: DMD Stats (the blocks), GitHub (the pool list and
logos) and the pools' APIs (MiningCore, YIIMP), on this machine."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from dmdmining import db, fetch, push
from dmdmining.config import Settings

NOW = 1_795_400_000
DIFFICULTY = 724_696.85

POOLS_V2 = [
    {
        "id": 1,
        "name": "Official",
        "addresses": ["DHa5vRtz46ENeVdLFjjDSwvWirEejuZrkZ"],
        "tags": ["Official"],
        "link": "https://pool.debitmydata.io/",
        "country": "US",
    },
    {
        "id": 3,
        "name": "MinorPool",
        "addresses": ["DHWaU1S9mCs142hsVvcJeTYG6VTycYLrvn"],
        "tags": [],
        "link": "https://minorpool.com/#Debitmydata",
        "country": "Turkey",
    },
    {
        "id": 6,
        "name": "CyberPool",
        "addresses": ["dm1q2qq63g00kertw7qq7a5jzhp6ve7npuljyr82t7"],
        "tags": ["CyberPool"],
        "link": "https://cyberpool.pro",
        "country": "US",
    },
    {
        "id": 9,
        "name": "Shears",
        "addresses": ["dm1q202l4t70q2q2h56skfy8luzqy6xrx4f8mnjted"],
        "tags": ["Shears Mining"],
        "link": "https://sha256-mining.shears.co.uk",
        "country": "United Kingdom",
    },
]


def block_hash(height: int, salt: str = "") -> str:
    return hashlib.sha256(f"{height}{salt}".encode()).hexdigest()


def miner_of(height: int) -> tuple[str, str | None]:
    k = height % 20
    if k < 11:
        return "the DebitMyData pool", "official"
    if k < 18:
        return "CyberPool", "cyberpool"
    if k < 19:
        return "MinorPool", "minorpool"
    return "SoloMiner", None


class World:
    """What the stand-in sites answer: change it in a test, the next read sees it."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.blocks: list[dict[str, Any]] = []
        self.add_blocks(2000, end=NOW - 60)
        self.info = {
            "pools": [
                {
                    "id": 1,
                    "title": "DebitMyData pool",
                    "software": "YIIMP",
                    "api": f"{base}/yiimp/api",
                    "api_coin": "DMD",
                    "modes": [
                        {
                            "label": "Shared",
                            "scheme": "PPLNS",
                            "fee": 0.5,
                            "stratum": ["connect.debitmydata.io:8700"],
                            "password": "x",
                        },
                        {
                            "label": "Solo",
                            "scheme": "SOLO",
                            "fee": 1,
                            "stratum": ["connect.debitmydata.io:8700"],
                            "password": "m=solo",
                        },
                    ],
                },
                {
                    "id": 3,
                    "software": "MiningCore",
                    "api": f"{base}/minor/api",
                    "hosts": ["minorpool.com"],
                    "modes": [
                        {"label": "PPLNS", "api_id": "Debitmydata"},
                        {"label": "Solo", "api_id": "Debitmydata-S"},
                    ],
                },
                {
                    "id": 6,
                    "software": "MiningCore",
                    "api": f"{base}/cyber/api",
                    "hosts": ["cyberpool.pro"],
                    "modes": [{"label": "Solo", "api_id": "dmd1"}],
                },
                {
                    "id": 9,
                    "software": "Custom",
                    "account": True,
                    "modes": [
                        {
                            "label": "Solo",
                            "scheme": "SOLO",
                            "fee": 0,
                            "stratum": ["stratum.shears.co.uk:3620"],
                        }
                    ],
                },
            ]
        }
        self.down: set[str] = set()
        self.cyber_height: int | None = None
        self.logos = {
            "official": b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>',
            "cyberpool": b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="4"/></svg>',
            "minorpool": b'<svg onload="alert(1)" xmlns="http://www.w3.org/2000/svg"/>',
            "default": b'<svg xmlns="http://www.w3.org/2000/svg"/>',
        }
        self.requests: list[str] = []

    def add_blocks(self, n: int, end: int | None = None, start_height: int | None = None) -> None:
        height = start_height if start_height is not None else len(self.blocks)
        end = end if end is not None else (self.blocks[-1]["time"] + 150 * n)
        for k in range(n):
            h = height + k
            miner, slug = miner_of(h)
            block = {
                "height": h,
                "hash": block_hash(h),
                "time": end - (n - 1 - k) * 150,
                "difficulty": DIFFICULTY,
                "miner": miner,
                "slug": slug,
                "pool": slug == "official",
                "coinbase_text": "",
                "transactions": 1,
                "size": 250,
                "reward_dmd": 35.0,
            }
            if h < len(self.blocks):
                self.blocks[h] = block
            else:
                self.blocks.append(block)

    @property
    def tip(self) -> int:
        return self.blocks[-1]["height"]

    def csv(self) -> bytes:
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(
            [
                "height",
                "time_utc",
                "hash",
                "difficulty",
                "transactions",
                "size_bytes",
                "pool",
                "coinbase_text",
                "mining_cost_usd",
                "miner",
                "volume_dmd",
                "fees_dmd",
            ]
        )
        for b in self.blocks:
            when = datetime.fromtimestamp(b["time"], UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            w.writerow(
                [
                    b["height"],
                    when,
                    b["hash"],
                    b["difficulty"],
                    1,
                    250,
                    1 if b["pool"] else 0,
                    "",
                    "0.0001",
                    b["miner"],
                    "",
                    "0",
                ]
            )
        return out.getvalue().encode()

    def answer(self, path: str) -> tuple[int, bytes, str]:
        self.requests.append(path)
        route = path.split("?")[0]
        if route == "/stats/api/blocks.json":
            latest = list(reversed(self.blocks[-1000:]))
            return 200, json.dumps({"blocks": latest, "count": len(latest)}).encode(), "json"
        if route == "/stats/api/dmd-blocks.csv":
            return 200, self.csv(), "csv"
        if route == "/github/pools/pools-v2.json":
            return 200, json.dumps(POOLS_V2).encode(), "json"
        if route == "/github/pools/pools-info.json":
            return 200, json.dumps(self.info).encode(), "json"
        if route.startswith("/github/logos/"):
            name = route.rsplit("/", 1)[1].removesuffix(".svg")
            if name in self.logos:
                return 200, self.logos[name], "svg"
            return 404, b"", "text"
        pool = route.split("/")[1]
        if pool in self.down:
            return 503, b"down", "text"
        if route == "/cyber/api/pools":
            return (
                200,
                json.dumps(
                    {"pools": [self.miningcore("dmd1", "SOLO", 1, 9.06e12, 2, self.cyber_height)]}
                ).encode(),
                "json",
            )
        if route == "/cyber/api/pools/dmd1/blocks":
            rows = [
                {
                    "blockHeight": b["height"],
                    "hash": b["hash"],
                    "status": "confirmed",
                    "effort": 1.25,
                    "reward": 35,
                    "created": "2026-11-22T15:41:54.054351",
                    "miner": "dm1qminer",
                }
                for b in self.blocks[-200:]
                if b["slug"] == "cyberpool"
            ]
            rows.append(
                {
                    "blockHeight": self.tip - 3,
                    "hash": block_hash(self.tip - 3, "orphan"),
                    "status": "orphaned",
                    "effort": 0.4,
                    "reward": 0,
                    "created": "2026-11-22T15:30:00",
                    "miner": "dm1qminer",
                }
            )
            return 200, json.dumps(rows).encode(), "json"
        if route == "/minor/api/pools":
            return (
                200,
                json.dumps(
                    {
                        "pools": [
                            self.miningcore("Debitmydata", "PPLNS", 1, 0, 0, None),
                            self.miningcore("Debitmydata-S", "SOLO", 2, 1.1e12, 1, None),
                            {"id": "salvium1", "coin": {"symbol": "SAL"}},
                        ]
                    }
                ).encode(),
                "json",
            )
        if route.startswith("/minor/api/pools/") and route.endswith("/blocks"):
            return 200, b"[]", "json"
        if route == "/yiimp/api/currencies":
            return (
                200,
                json.dumps(
                    {
                        "DMD": {
                            "algo": "sha256",
                            "port": 8700,
                            "name": "DebitMyData",
                            "height": self.tip,
                            "workers": 9,
                            "hashrate": 12.8e12,
                            "lastblock": self.tip,
                            "timesincelast": 60,
                        }
                    }
                ).encode(),
                "json",
            )
        if route == "/yiimp/api/status":
            return 200, json.dumps({"sha256": {"port": 8700, "fees": 0.5}}).encode(), "json"
        return 404, b"not found", "text"

    def miningcore(
        self,
        pool_id: str,
        scheme: str,
        fee: float,
        hashrate: float,
        miners: int,
        height: int | None,
    ) -> dict[str, Any]:
        return {
            "id": pool_id,
            "coin": {"type": "DMD", "name": "DebitMyData", "symbol": "DMD"},
            "ports": {
                "3059": {"difficulty": 65536, "tls": False},
                "3092": {
                    "name": "Auto",
                    "difficulty": 16384,
                    "varDiff": {"minDiff": 16384, "maxDiff": 10485760},
                },
            },
            "paymentProcessing": {"minimumPayment": 1, "payoutScheme": scheme},
            "poolFeePercent": fee,
            "poolStats": {"connectedMiners": miners, "poolHashrate": hashrate},
            "networkStats": {
                "blockHeight": height if height is not None else self.tip,
                "networkHashrate": 2.2e13,
            },
            "totalBlocks": 58187,
            "totalPaid": 1999811.4,
            "poolEffort": 0.2,
            "lastPoolBlockTime": "2026-11-22T15:41:54.054351",
        }


@pytest.fixture
def world() -> Iterator[World]:
    holder: dict[str, World] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status, body, kind = holder["w"].answer(self.path)
            self.send_response(status)
            types = {"json": "application/json", "csv": "text/csv", "svg": "image/svg+xml"}
            self.send_header("Content-Type", types.get(kind, "text/plain"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    holder["w"] = World(base)
    fetch.TEST_HOSTS.add(f"127.0.0.1:{server.server_address[1]}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield holder["w"]
    server.shutdown()
    fetch.TEST_HOSTS.clear()


@pytest.fixture
def settings(tmp_path: Path, world: World) -> Settings:
    return Settings(
        data_dir=tmp_path,
        public_dir=tmp_path / "public",
        site_url="https://mining.debitmydata.io",
        stats_url=f"{world.base}/stats",
        pools_url=f"{world.base}/github/pools",
        logos_url=f"{world.base}/github/logos",
        explorer_url="https://mempool.debitmydata.io",
        poll_seconds=60,
        chain_seconds=20,
        catalog_seconds=3600,
        push_listen="127.0.0.1:0",
        push_subject="mailto:test@example.com",
        push_max_devices=3,
        push_key_file=tmp_path / "push" / "vapid.pem",
    )


@pytest.fixture
def conn(settings: Settings) -> Any:
    connection = db.connect(settings.database)
    yield connection
    connection.close()


@pytest.fixture
def keys(settings: Settings) -> push.Keys:
    return push.make_keys(settings.push_key_file)[0]
