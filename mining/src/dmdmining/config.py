"""The settings, from the environment (/etc/dmd-mining/mining.env on the server)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    public_dir: Path
    site_url: str
    stats_url: str
    pools_url: str
    logos_url: str
    explorer_url: str
    poll_seconds: int
    chain_seconds: int
    catalog_seconds: int
    push_listen: str
    push_subject: str
    push_max_devices: int
    push_key_file: Path

    @property
    def database(self) -> Path:
        return self.data_dir / "mining.sqlite3"

    @property
    def catalog_dir(self) -> Path:
        """pools-v2.json, pools-info.json and the logos, as GitHub had them last time."""
        return self.data_dir / "pools"

    @classmethod
    def from_env(cls) -> Settings:
        data = Path(_str("DMDM_DATA_DIR", "/var/lib/dmd-mining"))
        return cls(
            data_dir=data,
            public_dir=Path(_str("DMDM_PUBLIC_DIR", str(data / "public"))),
            site_url=_str("DMDM_SITE_URL", "https://mining.debitmydata.io").rstrip("/"),
            stats_url=_str("DMDM_STATS_URL", "https://stats.debitmydata.io").rstrip("/"),
            pools_url=_str(
                "DMDM_POOLS_URL",
                "https://raw.githubusercontent.com/DebitMyData-PoW/mining-pools/master",
            ).rstrip("/"),
            logos_url=_str(
                "DMDM_LOGOS_URL",
                "https://raw.githubusercontent.com/DebitMyData-PoW/mining-pool-logos/master",
            ).rstrip("/"),
            explorer_url=_str("DMDM_EXPLORER_URL", "https://mempool.debitmydata.io").rstrip("/"),
            poll_seconds=max(30, _int("DMDM_POLL_SECONDS", 60)),
            chain_seconds=max(10, _int("DMDM_CHAIN_SECONDS", 20)),
            catalog_seconds=max(300, _int("DMDM_CATALOG_SECONDS", 3600)),
            push_listen=_str("DMDM_PUSH_LISTEN", "127.0.0.1:8481"),
            push_subject=_str("DMDM_PUSH_SUBJECT", "mailto:info@debitmydata.com"),
            push_max_devices=_int("DMDM_PUSH_MAX_DEVICES", 20000),
            push_key_file=Path(_str("DMDM_PUSH_KEY_FILE", str(data / "push" / "vapid.pem"))),
        )
