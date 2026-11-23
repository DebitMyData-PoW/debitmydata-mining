from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from dmdmining import adapters, api, catalog, chain, cli, db, fetch, notify, poller, publish
from dmdmining.config import Settings

from .conftest import NOW, POOLS_V2, World, block_hash


def setup(conn: sqlite3.Connection, settings: Settings) -> catalog.Catalog:
    cat = catalog.refresh(settings.pools_url, settings.logos_url, settings.catalog_dir)
    chain.follow(conn, settings.stats_url, cat, NOW)
    return cat


def events(conn: sqlite3.Connection, kind: str | None = None) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    return [
        {**dict(r), "data": json.loads(r["data"])}
        for r in rows
        if kind is None or r["kind"] == kind
    ]


# --------------------------------------------------------------------------- the pool list


def test_the_pool_list(settings: Settings, world: World) -> None:
    cat = catalog.refresh(settings.pools_url, settings.logos_url, settings.catalog_dir)
    pools = cat.by_slug()
    assert [p.slug for p in cat.pools] == ["official", "minorpool", "cyberpool", "shears"]
    assert pools["official"].display == "DebitMyData pool"
    assert pools["official"].modes[1].password == "m=solo"
    assert pools["official"].modes[0].stratum == ("connect.debitmydata.io:8700",)
    assert pools["cyberpool"].software == "MiningCore" and pools["cyberpool"].hosts == (
        "cyberpool.pro",
    )
    assert pools["shears"].account and pools["shears"].modes[0].scheme == "SOLO"
    assert catalog.country_code("United Kingdom") == "GB" and catalog.country_code("US") == "US"
    # logos: plain pictures only (MinorPool's has a script: left out)
    assert cat.logos == {"official", "cyberpool", "default"}
    # a broken list changes nothing
    world.info = "not json"  # type: ignore[assignment]
    again = catalog.refresh(settings.pools_url, settings.logos_url, settings.catalog_dir)
    assert again.by_slug()["official"].display == "DebitMyData pool"


def test_bad_entries_are_left_out() -> None:
    v2 = json.dumps([*POOLS_V2, {"id": 1, "name": "Copy"}, {"id": 300, "name": "Big"}, {"name": 5}])
    info = json.dumps(
        {
            "pools": [
                {
                    "id": 6,
                    "api": "http://169.254.169.254/latest",
                    "modes": [
                        {
                            "label": "x" * 99,
                            "scheme": "WHATEVER",
                            "fee": 500,
                            "stratum": ["bad host!:1", "ok.io:3"],
                        }
                    ],
                }
            ]
        }
    )
    pools = {p.slug: p for p in catalog.parse(v2.encode(), info.encode())}
    assert set(pools) == {"official", "minorpool", "cyberpool", "shears"}
    cyber = pools["cyberpool"]
    assert cyber.api == ""  # not https
    assert cyber.modes[0].scheme == "" and cyber.modes[0].fee is None
    assert cyber.modes[0].stratum == ("ok.io:3",) and len(cyber.modes[0].label) == 30
    with pytest.raises(ValueError):
        catalog.parse(b"{}", None)


def test_only_public_https_addresses() -> None:
    for url in (
        "http://example.com/api",
        "https://127.0.0.1/api",
        "https://localhost/x",
        "https://10.0.0.1/",
        "https://user:pw@example.com/",
    ):
        with pytest.raises(fetch.FetchError):
            fetch.check_url(url)


# --------------------------------------------------------------------------- the chain


def test_the_chain_from_dmd_stats(
    conn: sqlite3.Connection, settings: Settings, world: World
) -> None:
    cat = setup(conn, settings)
    n = conn.execute("SELECT count(*) AS n, max(height) AS h FROM blocks").fetchone()
    assert n["n"] == 2000 and n["h"] == world.tip
    assert events(conn) == []  # the first read tells nothing
    named = conn.execute("SELECT miner, slug, reward FROM blocks WHERE height = 11").fetchone()
    assert dict(named) == {"miner": "CyberPool", "slug": "cyberpool", "reward": 35.0}
    # two new blocks: two events
    world.add_blocks(2)
    assert chain.follow(conn, settings.stats_url, cat, NOW + 300) == 2
    found = events(conn, "block")
    assert [e["data"]["height"] for e in found] == [world.tip - 1, world.tip]
    # a reorganization replaces the last block: told as a new one
    world.blocks[-1]["hash"] = block_hash(world.tip, "reorg")
    world.blocks[-1]["miner"], world.blocks[-1]["slug"] = "CyberPool", "cyberpool"
    assert chain.follow(conn, settings.stats_url, cat, NOW + 320) == 1
    assert events(conn, "block")[-1]["slug"] == "cyberpool"
    # named again (the pool list changed): not a new block
    world.blocks[-5]["miner"], world.blocks[-5]["slug"] = "Shears", "shears"
    assert chain.follow(conn, settings.stats_url, cat, NOW + 340) == 0
    assert (
        conn.execute("SELECT slug FROM blocks WHERE height = ?", (world.tip - 4,)).fetchone()[
            "slug"
        ]
        == "shears"
    )
    assert len(events(conn, "block")) == 3


def test_subsidy() -> None:
    assert chain.subsidy(1) == 35 and chain.subsidy(300_000) == 17.5
    assert chain.subsidy(9_600_000) == 35  # DebitMyData's cycle starts again


# --------------------------------------------------------------------------- the pools' APIs


def test_the_pools_apis(conn: sqlite3.Connection, settings: Settings, world: World) -> None:
    cat = setup(conn, settings)
    states = poller.poll(conn, cat, NOW)
    assert states["cyberpool"]["ok"] and states["cyberpool"]["hashrate"] == 9.06e12
    cyber = states["cyberpool"]["modes"][0]
    assert cyber["scheme"] == "SOLO" and cyber["fee"] == 1 and cyber["min_payout"] == 1
    assert [p["port"] for p in cyber["ports"]] == [3059, 3092]
    assert cyber["ports"][1]["vardiff"] == {"min": 16384, "max": 10485760}
    minor = states["minorpool"]
    assert [m["label"] for m in minor["modes"]] == ["PPLNS", "Solo"]
    assert minor["hashrate"] == 1.1e12 and minor["miners"] == 1
    official = states["official"]
    assert official["hashrate"] == 12.8e12 and official["workers"] == 9
    assert [m["fee"] for m in official["modes"]] == [0.5, 1]
    shears = states["shears"]
    assert not shears["api"] and shears["problem"] == ""
    # MiningCore's blocks, with their status
    statuses = dict(
        conn.execute(
            "SELECT status, count(*) FROM pool_blocks WHERE slug = 'cyberpool' GROUP BY status"
        )
    )
    assert statuses["orphaned"] == 1 and statuses["confirmed"] > 50
    # a pool that stops answering: told after 10 minutes, then when it's back
    world.down.add("cyber")
    for minute in range(1, 12):
        poller.poll(conn, cat, NOW + 60 * minute)
    down = events(conn, "pool_down")
    assert len(down) == 1 and down[0]["slug"] == "cyberpool" and down[0]["data"]["reason"] == "down"
    world.down.clear()
    poller.poll(conn, cat, NOW + 60 * 12)
    assert [e["slug"] for e in events(conn, "pool_up")] == ["cyberpool"]
    # its node behind the chain
    world.cyber_height = world.tip - 20
    for minute in range(13, 25):
        poller.poll(conn, cat, NOW + 60 * minute)
    assert events(conn, "pool_down")[-1]["data"]["reason"] == "behind"


def test_a_pool_the_api_no_longer_lists(
    conn: sqlite3.Connection, settings: Settings, world: World
) -> None:
    cat = setup(conn, settings)
    world.info["pools"][2]["modes"][0]["api_id"] = "dmd-gone"
    cat = catalog.refresh(settings.pools_url, settings.logos_url, settings.catalog_dir)
    state = poller.poll(conn, cat, NOW)["cyberpool"]
    assert not state["ok"] and "no longer" in state["error"]


def test_miningcore_without_modes_finds_dmd(world: World) -> None:
    pool = catalog.Pool(
        id=3,
        name="MinorPool",
        slug="minorpool",
        software="MiningCore",
        api=f"{world.base}/minor/api",
    )
    figures = adapters.read(pool, NOW, False)
    assert [m.api_id for m in figures.modes] == ["Debitmydata", "Debitmydata-S"]
    assert [m.label for m in figures.modes] == ["Pplns", "Solo"]


def test_majority(conn: sqlite3.Connection, settings: Settings, world: World) -> None:
    setup(conn, settings)
    poller.majority(conn, NOW)  # the pool has 11 blocks in 20: 55%
    first = events(conn, "majority")
    assert len(first) == 1 and first[0]["slug"] == "official" and first[0]["data"]["share"] > 0.5
    poller.majority(conn, NOW)
    assert len(events(conn, "majority")) == 1  # once
    for b in world.blocks[-144:]:
        b["miner"], b["slug"] = "CyberPool", "cyberpool"
    world.blocks[-1]["hash"] = block_hash(world.tip, "x")
    chain.store(conn, [dict(b, reward=35, tx=1, size=250) for b in world.blocks[-144:]], NOW, False)
    poller.majority(conn, NOW + 60)
    assert [e["kind"] for e in events(conn) if e["kind"].startswith("majority")] == [
        "majority",
        "majority_end",
    ]


# --------------------------------------------------------------------------- the site's files


def test_the_site_files(conn: sqlite3.Connection, settings: Settings, world: World) -> None:
    cat = setup(conn, settings)
    for minute in range(0, 120, 1):
        poller.poll(conn, cat, NOW - 7200 + 60 * minute)
    poller.aggregate(conn, NOW)
    cli.publish_logos(settings, cat)
    publish.publish(conn, cat, settings.public_dir, NOW, settings.explorer_url, slow_too=True)
    api_dir = settings.public_dir / "api"
    summary = json.loads((api_dir / "summary.json").read_text())
    net = summary["network"]
    assert net["height"] == world.tip and net["block_seconds_24h"] == 150.0
    assert net["hashrate_24h"] == pytest.approx(724_696.85 * 2**32 / 150, rel=0.01)
    pools = {p["slug"]: p for p in summary["pools"]}
    assert [p["slug"] for p in summary["pools"]][:2] == ["official", "cyberpool"]
    official = pools["official"]
    assert official["blocks"]["24h"] == 576 * 11 // 20 + 1 or official["blocks"]["24h"] in range(
        310, 322
    )
    assert official["logo"] == "/logos/official.svg" and pools["minorpool"]["logo"] is None
    assert official["flag"] == "🇺🇸" and pools["shears"]["country_code"] == "GB"
    assert official["schemes"] == ["PPLNS", "SOLO"] and official["fee_min"] == 0.5
    assert pools["cyberpool"]["solo_only"] and pools["shears"]["status"] == "none"
    assert len(official["spark"]) == 24 and official["spark"][-1] == 12.8e12
    assert pools["shears"]["spark"] == [0] * 24
    luck = pools["cyberpool"]["luck_24h"]
    assert luck is None  # two hours of figures: not enough for 24 hours
    assert summary["others"][0]["name"] == "SoloMiner"
    assert summary["totals"]["nakamoto_24h"] == 1 and summary["totals"]["pools_answering"] == 3
    # the distribution
    dist = json.loads((api_dir / "distribution.json").read_text())
    assert dist["1000"]["blocks"] == 1000
    assert dist["24h"]["miners"][0]["name"] == "DebitMyData pool"
    assert {m["name"] for m in dist["all"]["miners"]} == {
        "DebitMyData pool",
        "CyberPool",
        "MinorPool",
        "SoloMiner",
    }
    # charts
    day = json.loads((api_dir / "chart-24h.json").read_text())
    assert len(day["hashrate"]["times"]) in (288, 289)
    names = [s["slug"] for s in day["hashrate"]["pools"]]
    assert set(names) == {"official", "cyberpool", "minorpool"}
    cyber = next(s for s in day["hashrate"]["pools"] if s["slug"] == "cyberpool")
    assert cyber["values"][-2] == 9.06e12 and cyber["values"][0] is None
    assert day["blocks"]["series"][-1]["name"] == "Other miners"
    # each pool's hashrate from its blocks: together, the network's
    found = day["hashrate"]["from_blocks"]
    assert [f["key"] for f in found][:2] == ["official", "cyberpool"] and found[-1][
        "key"
    ] == "others"
    for k in (5, 100, 250):
        together = sum(f["values"][k] for f in found)
        assert together == pytest.approx(day["hashrate"]["network"][k], rel=0.001)
    everything = json.loads((api_dir / "chart-all.json").read_text())["hashrate"]["from_blocks"]
    assert sum(everything[0]["values"]) > 0
    assert 540 <= sum(sum(s["values"]) for s in day["blocks"]["series"]) <= 577
    for name in ("7d", "30d", "1y", "all"):
        assert json.loads((api_dir / f"chart-{name}.json").read_text())["range"] == name
    # one pool's page
    detail = json.loads((api_dir / "pools" / "cyberpool.json").read_text())
    urls = [e["url"] for e in detail["modes"][0]["endpoints"]]
    assert urls == ["stratum+tcp://cyberpool.pro:3059", "stratum+tcp://cyberpool.pro:3092"]
    assert detail["found"][0]["status"] in ("confirmed", None) and detail["orphaned"]
    assert detail["effort_30d"] is not None and detail["uptime_24h"] == 1.0
    assert detail["seconds_per_block"] == pytest.approx(724_696.85 * 2**32 / 9.06e12, rel=0.01)
    shears = json.loads((api_dir / "pools" / "shears.json").read_text())
    assert shears["modes"][0]["endpoints"][0]["url"] == "stratum+tcp://stratum.shears.co.uk:3620"
    official_detail = json.loads((api_dir / "pools" / "official.json").read_text())
    assert official_detail["charts"]["24h"]["reported"][-2] == 12.8e12
    assert len(official_detail["charts"]["7d"]["blocks"]["values"]) in (28, 29)
    latest = json.loads((api_dir / "blocks.json").read_text())["blocks"]
    assert latest[0]["height"] == world.tip and latest[0]["seconds"] == 150
    assert (settings.public_dir / "logos" / "official.svg").exists()


def test_nakamoto() -> None:
    assert publish.nakamoto([55, 40, 5]) == 1
    assert publish.nakamoto([40, 35, 25]) == 2
    assert publish.nakamoto([]) is None


# --------------------------------------------------------------------------- notifications


SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
    "keys": {
        "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
        "auth": "tBHItJI5svbpez7KI4CCXg",
    },
}


def test_the_notifications_api(settings: Settings, keys: Any, conn: sqlite3.Connection) -> None:
    push_api = api.PushApi(str(settings.database), keys, settings.site_url, 3)
    assert push_api.config()["key"] == keys.public
    on = push_api.handle(
        {"action": "subscribe", "subscription": SUB, "prefs": {"pools": ["cyberpool"]}}
    )
    assert on["on"] and on["prefs"] == {"pools": ["cyberpool"], "problems": True, "majority": False}
    changed = push_api.handle(
        {
            "action": "update",
            "endpoint": SUB["endpoint"],
            "prefs": {"pools": ["official"], "majority": True},
        }
    )
    assert changed["prefs"]["pools"] == ["official"] and changed["prefs"]["majority"]
    assert push_api.handle({"action": "test", "endpoint": SUB["endpoint"]}) == {"ok": True}
    with pytest.raises(api.Refused) as refused:
        push_api.handle({"action": "test", "endpoint": SUB["endpoint"]})
    assert refused.value.status == 429
    for bad in ({"pools": ["not a slug"]}, {"pools": [f"p{n}" for n in range(21)]}, "nope"):
        with pytest.raises(api.Refused):
            push_api.handle({"action": "update", "endpoint": SUB["endpoint"], "prefs": bad})
    elsewhere = {**SUB, "endpoint": "https://evil.example.com/push"}
    with pytest.raises(api.Refused):
        push_api.handle({"action": "subscribe", "subscription": elsewhere})
    new = {**SUB, "endpoint": "https://fcm.googleapis.com/fcm/send/new"}
    assert push_api.handle({"action": "renew", "old": SUB["endpoint"], "subscription": new})["ok"]
    assert push_api.handle({"action": "get", "endpoint": new["endpoint"]})["on"]
    assert push_api.handle({"action": "unsubscribe", "endpoint": new["endpoint"]}) == {"on": False}
    assert conn.execute("SELECT count(*) AS n FROM devices").fetchone()["n"] == 0


def test_what_each_device_is_told(
    conn: sqlite3.Connection, settings: Settings, world: World
) -> None:
    cat = setup(conn, settings)
    names = {p.slug: p.display for p in cat.pools}
    world.add_blocks(3)
    chain.follow(conn, settings.stats_url, cat, NOW + 450)
    poller._event(conn, NOW, "pool_down", "cyberpool", {"reason": "behind", "height": 5, "tip": 30})
    poller._event(conn, NOW, "pool_down", "minorpool", {"reason": "down"})
    poller._event(
        conn,
        NOW,
        "majority",
        "official",
        {"who": "official", "miner": "the DebitMyData pool", "share": 0.55, "of": 144},
    )
    conn.execute(
        "INSERT INTO devices (endpoint, endpoint_hash, p256dh, auth, prefs, cursor, created_at, "
        "updated_at) VALUES ('e', 'h', 'k', 'a', ?, 0, 0, 0)",
        (json.dumps({"pools": ["official", "cyberpool"], "problems": True, "majority": True}),),
    )
    device = conn.execute("SELECT * FROM devices").fetchone()
    rows = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    notices, cursor = notify.collect(device, rows, names)
    titles = [n["title"] for n in notices]
    tip_miners = [chain.slug_for(b["miner"], cat) for b in world.blocks[-3:]]
    assert cursor == rows[-1]["id"]
    expected_blocks = {"official": "DebitMyData pool", "cyberpool": "CyberPool"}
    for slug in set(tip_miners) & set(expected_blocks):
        count = tip_miners.count(slug)
        word = "a block" if count == 1 else f"{count} blocks"
        assert f"{expected_blocks[slug]} found {word}" in titles
    assert "CyberPool's node is behind" in titles
    assert not any("MinorPool" in t for t in titles)  # not followed
    assert "One miner finds most blocks" in titles
    majority = next(n for n in notices if n["tag"] == "majority")
    assert "DebitMyData pool found 55%" in majority["body"]
    # nothing twice
    conn.execute("UPDATE devices SET cursor = ?", (cursor,))
    device = conn.execute("SELECT * FROM devices").fetchone()
    assert notify.collect(device, rows, names) == ([], cursor)


def test_notices_reach_the_push_service(
    conn: sqlite3.Connection, settings: Settings, keys: Any, world: World, monkeypatch: Any
) -> None:
    from dmdmining import push

    sent: list[tuple[str, dict[str, Any]]] = []

    def deliver(
        k: Any, subject: str, device: dict[str, Any], message: dict[str, Any]
    ) -> tuple[int, str]:
        sent.append((device["endpoint"], message))
        return (410, "gone") if device["endpoint"].endswith("old") else (201, "")

    monkeypatch.setattr(push, "deliver", deliver)
    cat = setup(conn, settings)
    push_api = api.PushApi(str(settings.database), keys, settings.site_url, 3)
    push_api.handle({"action": "subscribe", "subscription": SUB, "prefs": {"pools": ["official"]}})
    stale = {**SUB, "endpoint": "https://fcm.googleapis.com/fcm/send/old"}
    push_api.handle(
        {"action": "subscribe", "subscription": stale, "prefs": {"pools": ["official"]}}
    )
    notifier = notify.Notifier(conn, keys, settings.push_subject)
    assert notifier.run_once(cat, NOW) == 0
    world.add_blocks(20)
    chain.follow(conn, settings.stats_url, cat, NOW + 3000)
    assert notifier.run_once(cat, NOW + 3000) == 1
    assert sent[-1][1]["title"].startswith("DebitMyData pool found")
    assert (
        conn.execute("SELECT count(*) AS n FROM devices").fetchone()["n"] == 1
    )  # the stale one went
    answer = push_api.handle({"action": "get", "endpoint": SUB["endpoint"]})
    assert answer["items"][0]["url"] == "/pool/official"
    assert notifier.run_once(cat, NOW + 3020) == 0


def test_status_command(
    conn: sqlite3.Connection, settings: Settings, world: World, capsys: Any, monkeypatch: Any
) -> None:
    cat = setup(conn, settings)
    poller.poll(conn, cat, NOW)
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Blocks: 2000" in out and "cyberpool" in out and "no API" in out


def test_files_have_no_secret(
    settings: Settings, conn: sqlite3.Connection, world: World, keys: Any
) -> None:
    cat = setup(conn, settings)
    poller.poll(conn, cat, NOW)
    publish.publish(conn, cat, settings.public_dir, NOW, settings.explorer_url, slow_too=True)
    for path in Path(settings.public_dir).rglob("*.json"):
        text = path.read_text()
        assert "PRIVATE KEY" not in text and "p256dh" not in text and "googleapis" not in text
    assert db.get(conn, "polled_at") == NOW


def test_the_service(settings: Settings, world: World, keys: Any) -> None:
    service = cli.Service(settings)
    service.round()  # the pool list, every block, the pools' APIs, the files
    summary = json.loads((settings.public_dir / "api" / "summary.json").read_text())
    assert summary["network"]["height"] == world.tip
    assert {p["slug"] for p in summary["pools"]} == {"official", "minorpool", "cyberpool", "shears"}
    assert (settings.public_dir / "logos" / "cyberpool.svg").exists()
    # a pool list read by `dmd-mining pools` is taken within the next rounds
    world.info["pools"][0]["title"] = "The DebitMyData pool"
    catalog.refresh(settings.pools_url, settings.logos_url, settings.catalog_dir)
    service.next["reload"] = 0
    service.round()
    assert service.catalog.by_slug()["official"].display == "The DebitMyData pool"
    world.add_blocks(1)
    service.next["chain"] = 0
    service.round()
    blocks = json.loads((settings.public_dir / "api" / "blocks.json").read_text())["blocks"]
    assert blocks[0]["height"] == world.tip
