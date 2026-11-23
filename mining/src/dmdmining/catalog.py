"""DebitMyData's pool list, from GitHub, as the other DebitMyData sites read it:

  pools-v2.json    (DebitMyData-PoW/mining-pools) each pool's name, link, country, and how its
                   blocks are known: the text it writes in them (tags), the addresses it pays
  pools-info.json  (the same repository) what this site shows besides: the pool's API, its
                   stratum servers, its fees, how to connect (README there)
  <slug>.svg       (DebitMyData-PoW/mining-pool-logos) its logo

They are read again every hour (DMDM_CATALOG_SECONDS). Nothing from GitHub runs here: the lists
must read as lists, each logo as a plain picture (no script, no link out); anything else is left
out, and what was there before stays.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dmdmining import fetch

log = logging.getLogger(__name__)

SCHEMES = ("PPLNS", "PPS", "PPS+", "FPPS", "PROP", "SOLO", "PPLNT", "SCORE")
SOFTWARE = ("MiningCore", "YIIMP", "NOMP", "Custom")
MAX_LOGO = 3_000_000
UNSAFE_SVG = re.compile(
    rb"<script|<foreignobject|<iframe|<embed|<object|javascript:|\bon[a-z]+\s*=|"
    rb"(?:xlink:)?href\s*=\s*[\"'](?!#|data:image/)",
    re.I,
)
COUNTRIES = {
    "united states": "US",
    "usa": "US",
    "us": "US",
    "turkey": "TR",
    "türkiye": "TR",
    "united arab emirates": "AE",
    "uae": "AE",
    "united kingdom": "GB",
    "uk": "GB",
    "great britain": "GB",
    "germany": "DE",
    "france": "FR",
    "netherlands": "NL",
    "canada": "CA",
    "russia": "RU",
    "china": "CN",
    "hong kong": "HK",
    "singapore": "SG",
    "japan": "JP",
    "south korea": "KR",
    "korea": "KR",
    "india": "IN",
    "brazil": "BR",
    "australia": "AU",
    "finland": "FI",
    "sweden": "SE",
    "norway": "NO",
    "poland": "PL",
    "ukraine": "UA",
    "spain": "ES",
    "italy": "IT",
    "switzerland": "CH",
    "austria": "AT",
    "czechia": "CZ",
    "czech republic": "CZ",
    "romania": "RO",
    "bulgaria": "BG",
    "kazakhstan": "KZ",
    "vietnam": "VN",
    "thailand": "TH",
    "indonesia": "ID",
    "malaysia": "MY",
    "philippines": "PH",
    "argentina": "AR",
    "mexico": "MX",
    "south africa": "ZA",
    "nigeria": "NG",
    "iran": "IR",
    "portugal": "PT",
    "ireland": "IE",
    "belgium": "BE",
    "denmark": "DK",
    "lithuania": "LT",
    "latvia": "LV",
    "estonia": "EE",
    "georgia": "GE",
    "armenia": "AM",
    "israel": "IL",
    "saudi arabia": "SA",
    "qatar": "QA",
    "kuwait": "KW",
    "bahrain": "BH",
    "oman": "OM",
    "egypt": "EG",
    "morocco": "MA",
    "kenya": "KE",
    "chile": "CL",
    "colombia": "CO",
    "peru": "PE",
    "venezuela": "VE",
    "new zealand": "NZ",
    "taiwan": "TW",
    "pakistan": "PK",
}


def slug_of(name: str) -> str:
    """A pool's slug: its name's lowercase letters and digits ("Coin-Miners": coinminers), as DMD
    Stats and the analytics site write it, and as its logo is named."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def country_code(value: str) -> str:
    text = value.strip()
    if re.fullmatch(r"[A-Za-z]{2}", text):
        return text.upper()
    return COUNTRIES.get(text.lower(), "")


def _text(value: Any, limit: int = 300) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _number(value: Any, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if low <= value <= high else None


def _url(value: Any) -> str:
    text = _text(value, 500)
    if re.match(r"^https://[^\s\"'<>]+$", text):
        return text
    test = re.match(r"^http://([^/\s\"'<>]+)[^\s\"'<>]*$", text)
    return text if test and test.group(1) in fetch.TEST_HOSTS else ""


def _host(value: str) -> str:
    """ "host" or "host:port", without stratum+tcp:// in front."""
    text = re.sub(r"^stratum\+(?:tcp|ssl|tls)://", "", value.strip(), flags=re.I)
    return text if re.fullmatch(r"[A-Za-z0-9.-]{1,253}(?::\d{1,5})?", text) else ""


@dataclass(frozen=True)
class Mode:
    label: str
    api_id: str = ""
    scheme: str = ""
    fee: float | None = None
    min_payout: float | None = None
    stratum: tuple[str, ...] = ()
    password: str = ""
    note: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "api_id": self.api_id or None,
            "scheme": self.scheme or None,
            "fee": self.fee,
            "min_payout": self.min_payout,
            "stratum": list(self.stratum),
            "password": self.password or None,
            "note": self.note or None,
        }


@dataclass(frozen=True)
class Pool:
    id: int
    name: str
    slug: str
    link: str = ""
    country: str = ""
    addresses: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    title: str = ""
    website: str = ""
    software: str = ""
    api: str = ""
    api_coin: str = ""
    hosts: tuple[str, ...] = ()
    username: str = ""
    account: bool = False
    notes: str = ""
    modes: tuple[Mode, ...] = ()

    @property
    def display(self) -> str:
        return self.title or self.name

    @property
    def domain(self) -> str:
        url = self.website or self.link
        match = re.match(r"^https?://(?:www\.)?([^/:?#]+)", url)
        return match.group(1) if match else ""

    @property
    def solo_only(self) -> bool:
        return bool(self.modes) and all(m.scheme == "SOLO" for m in self.modes if m.scheme)


@dataclass(frozen=True)
class Catalog:
    pools: tuple[Pool, ...] = ()
    digest: str = ""
    logos: frozenset[str] = field(default_factory=frozenset)

    def by_slug(self) -> dict[str, Pool]:
        return {p.slug: p for p in self.pools}


def _modes(raw: Any) -> tuple[Mode, ...]:
    out = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        scheme = _text(entry.get("scheme"), 10).upper()
        stratum = tuple(
            h for h in (_host(s) for s in entry.get("stratum") or [] if isinstance(s, str)) if h
        )[:12]
        out.append(
            Mode(
                label=_text(entry.get("label"), 30) or scheme.title() or "Pool",
                api_id=_text(entry.get("api_id"), 60),
                scheme=scheme if scheme in SCHEMES else "",
                fee=_number(entry.get("fee"), 0, 100),
                min_payout=_number(entry.get("min_payout"), 0, 1e9),
                stratum=stratum,
                password=_text(entry.get("password"), 60),
                note=_text(entry.get("note")),
            )
        )
    return tuple(out[:6])


def parse(pools_v2: bytes, info: bytes | None) -> list[Pool]:
    """The pools in pools-v2.json, with what pools-info.json adds about each. Raises ValueError
    when pools-v2.json is not a list of pools (pools-info.json is optional)."""
    entries = json.loads(pools_v2)
    if not isinstance(entries, list) or not entries:
        raise ValueError("pools-v2.json is not a list of pools")
    extra: dict[int, dict[str, Any]] = {}
    if info:
        try:
            data = json.loads(info)
            for entry in data.get("pools", []) if isinstance(data, dict) else []:
                if isinstance(entry, dict) and isinstance(entry.get("id"), int):
                    extra[entry["id"]] = entry
        except ValueError:
            log.warning("pools-info.json is not JSON: left out")
    pools: list[Pool] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        number, slug = entry.get("id"), slug_of(entry["name"])
        if (
            not isinstance(number, int)
            or not 1 <= number <= 255
            or not slug
            or slug == "unknown"
            or any(p.slug == slug or p.id == number for p in pools)
        ):
            continue
        more = extra.get(number, {})
        software = _text(more.get("software"), 20)
        api = _url(more.get("api")).rstrip("/")
        pools.append(
            Pool(
                id=number,
                name=_text(entry["name"], 60),
                slug=slug,
                link=_url(entry.get("link")),
                country=_text(entry.get("country"), 60),
                addresses=tuple(
                    a for a in entry.get("addresses") or [] if isinstance(a, str) and a
                )[:50],
                tags=tuple(t for t in entry.get("tags") or [] if isinstance(t, str) and t)[:20],
                title=_text(more.get("title"), 60),
                website=_url(more.get("website")),
                software=next((s for s in SOFTWARE if s.lower() == software.lower()), ""),
                api=api,
                api_coin=_text(more.get("api_coin"), 20),
                hosts=tuple(
                    h
                    for h in (_host(x) for x in more.get("hosts") or [] if isinstance(x, str))
                    if h and ":" not in h
                )[:8],
                username=_text(more.get("username")),
                account=more.get("account") is True,
                notes=_text(more.get("notes"), 500),
                modes=_modes(more.get("modes")),
            )
        )
    pools.sort(key=lambda p: p.id)
    return pools


def safe_logo(data: bytes) -> bool:
    """A plain SVG picture: no script, no link out, no embedded page."""
    if b"<svg" not in data[:4096].lower():
        return False
    bare = re.sub(
        rb"data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]*", b"data:image/", data
    )
    return not UNSAFE_SVG.search(bare)


def _shrink(svg: bytes) -> bytes:
    """A heavy logo (a picture inside) made small: 96 pixels inside an SVG, as the pages draw it.
    Needs rsvg-convert (librsvg2-bin); without it, the logo stays as it is."""
    if len(svg) <= 150_000 or not shutil.which("rsvg-convert"):
        return svg
    with tempfile.TemporaryDirectory() as work:
        src, png = Path(work) / "in.svg", Path(work) / "out.png"
        src.write_bytes(svg)
        try:
            subprocess.run(
                [
                    "rsvg-convert",
                    "-w",
                    "96",
                    "-h",
                    "96",
                    "--keep-aspect-ratio",
                    str(src),
                    "-o",
                    str(png),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError):
            return svg
        import base64

        data = base64.b64encode(png.read_bytes()).decode()
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 96 96"><image width="96" height="96" '
            f'xlink:href="data:image/png;base64,{data}"/></svg>\n'
        ).encode()


def load(folder: Path) -> Catalog:
    """The list as it was last read from GitHub (an empty one before the first time)."""
    try:
        v2 = (folder / "pools-v2.json").read_bytes()
    except OSError:
        return Catalog()
    try:
        info = (folder / "pools-info.json").read_bytes()
    except OSError:
        info = None
    try:
        pools = parse(v2, info)
    except ValueError:
        return Catalog()
    digest = hashlib.sha256(v2 + b"\0" + (info or b"")).hexdigest()[:16]
    logos = frozenset(p.stem for p in (folder / "logos").glob("*.svg"))
    return Catalog(tuple(pools), digest, logos)


def _info_reads(data: bytes) -> bool:
    try:
        parsed = json.loads(data)
    except ValueError:
        return False
    return isinstance(parsed, dict) and isinstance(parsed.get("pools"), list)


def refresh(pools_url: str, logos_url: str, folder: Path) -> Catalog:
    """Reads the list and the logos from GitHub again, and keeps them in `folder`. Whatever can't be
    read keeps what was there."""
    logos_dir = folder / "logos"
    logos_dir.mkdir(parents=True, exist_ok=True)
    v2 = fetch.get(f"{pools_url}/pools-v2.json", limit=3_000_000)
    try:
        info: bytes | None = fetch.get(f"{pools_url}/pools-info.json", limit=1_000_000)
    except fetch.FetchError as exc:
        log.info("pools-info.json not read (%s): the last one read stays", exc)
        info = None
    if info is not None and not _info_reads(info):
        log.warning('pools-info.json doesn\'t read as {"pools": [...]}: the last good one stays')
        info = None
    if info is None:
        try:
            info = (folder / "pools-info.json").read_bytes()
        except OSError:
            info = None
    pools = parse(v2, info)  # ValueError: not a list, nothing changes
    _keep(folder / "pools-v2.json", v2)
    if info is not None:
        _keep(folder / "pools-info.json", info)
    for name in [p.slug for p in pools] + ["default", "unknown"]:
        wanted = [name]
        pool = next((p for p in pools if p.slug == name), None)
        if pool is not None:
            dashed = re.sub(r"[^a-z0-9-]", "", pool.name.lower())
            if dashed != name:
                wanted.append(dashed)
        for candidate in wanted:
            try:
                svg = fetch.get(f"{logos_url}/{candidate}.svg", limit=MAX_LOGO)
            except fetch.FetchError:
                continue
            if safe_logo(svg):
                _keep(logos_dir / f"{name}.svg", _shrink(svg))
            else:
                log.warning("logo %s.svg left out: not a plain picture", candidate)
            break
    return load(folder)


def _keep(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.chmod(0o644)
    tmp.replace(path)
