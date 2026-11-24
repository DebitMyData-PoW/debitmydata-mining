# DMD Mining

Every pool mining DMD (the DebitMyData coin), live, in one place:
**[mining.debitmydata.io](https://mining.debitmydata.io)**. Miners compare the pools and connect
in one tap; everyone sees who finds the blocks and how spread out mining is.

<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/mining-devices-dark.webp">
  <img src="docs/images/mining-devices-light.webp" alt="DMD Mining on a computer, and a pool's page on a phone" width="820">
</picture>
</p>

## What it shows

- **Every pool**, with its hashrate, miners, fees, payout schemes and status from its own API, and
  the blocks it found from the chain: over the last hour, day, week and month, its last block,
  its share of the blocks, its luck, and a chart of its last 24 hours.
- **A page for each pool**: how to connect (each stratum address with its difficulty, the username
  and password, copied in one tap), its hashrate and blocks over 24 hours, 7 days, 30 days and a
  year, the blocks it found with their status and effort, its addresses, how often its API
  answered, and whether its node is behind the chain.
- **The charts over time**: each pool's hashrate from the blocks it found (every block since
  block 1, every pool; together they make the network's), or as its own API says it, and the
  blocks each found, from 24 hours to everything.
- **Who finds the blocks**, and how concentrated mining is: how many miners together find half of
  them (a miner with more than half could rewrite recent blocks).
- **The latest blocks**, who found each and how long it took.
- **Notifications**: a notice on the device each time a pool it follows finds a block, even when
  the page is closed; optionally when a followed pool stops answering or its node falls behind,
  and when one miner finds more than half of the blocks. No account needed.
- **An open API**: the site's files, explained at
  [mining.debitmydata.io/api/](https://mining.debitmydata.io/api/).
- **An app**: it installs on phones and computers from the browser.

## Where the figures come from

| What | From | How often |
| :-- | :-- | :-- |
| Who found each block | [DMD Stats](https://stats.debitmydata.io/api/) (`blocks.json`, `dmd-blocks.csv`), which reads every block from its own node and names its miner from DebitMyData's pool list | every 20 seconds |
| The pools: names, links, countries, how their blocks are known | [`pools-v2.json`](https://github.com/DebitMyData-PoW/mining-pools) (the same list as the mempool explorer, DMD Stats and the analytics site) | every hour |
| Each pool's API, stratum servers, fees, how to connect | [`pools-info.json`](https://github.com/DebitMyData-PoW/mining-pools#readme), next to it | every hour |
| The logos | [mining-pool-logos](https://github.com/DebitMyData-PoW/mining-pool-logos) | every hour |
| Each pool's hashrate, miners, fee, ports, its node's height, its blocks' status | the pool's own API: MiningCore or YIIMP | every minute |

The site needs no node of its own. A pool without a public API (or with another kind) shows what
it found on the chain, and what `pools-info.json` says about it.

## The figures

- **A pool's hashrate**: what its API says (MiningCore: `poolHashrate`; YIIMP: the coin's
  hashrate, shared and solo together). Pools count differently, so their total can be more than
  the network's.
- **From its blocks**: the work of the blocks a pool found (difficulty × 2^32 each) divided by
  the time, over a window (2 hours on the 24-hour chart, more on the longer ones). It is the
  only hashrate of a pool without an API, and the way to check the others'.
- **The network's hashrate**: the same, with every block.
- **Luck**: the blocks a pool found, divided by the blocks its hashrate should have found at the
  difficulty of the time. Above 100%, it found more. **Effort** (MiningCore): the work a block
  took, against the work a block takes on average; under 100%, it was luckier.
- **Half the blocks by**: how many miners together found more than half of the blocks (the
  Nakamoto coefficient). 1 means one miner did.
- **A pool's node is behind** when its API says its node is more than 5 blocks behind the chain:
  its miners may be working on old blocks, and their blocks would be orphaned.

## The notifications

| Notice | When |
| :-- | :-- |
| *CyberPool found a block* | Each block a followed pool finds (several since the last notice make one) |
| *CyberPool isn't answering*, *CyberPool's node is behind*, *CyberPool is back* | A followed pool's API doesn't answer for 10 minutes, or its node is more than 5 blocks behind for 10 minutes; and when it's over (on by default) |
| *One miner finds most blocks*, *Mining is spread out again* | A miner finds more than half of the last 144 blocks (6 hours), and when it's back under 45% (off by default) |

Anyone can turn them on with a pool's bell or the Notifications card. The server keeps each
device's choices with its browser's push subscription, and nothing else: no account, no email, no
IP address. Turning them off removes both. Every notice is encrypted for its device.

## Adding a pool

A pool appears on the site once it is in DebitMyData's public pool list:

1. In [DebitMyData-PoW/mining-pools](https://github.com/DebitMyData-PoW/mining-pools), add it to
   `pools-v2.json` (the mempool explorer, DMD Stats and the analytics site see it too), and add an
   entry with its `id` in `pools-info.json` (its README explains each field). For a MiningCore
   pool, its API and its stratum hosts are enough:

   ```json
   {
     "id": 11,
     "website": "https://example-pool.com/dmd",
     "software": "MiningCore",
     "api": "https://example-pool.com/api",
     "hosts": ["example-pool.com"],
     "modes": [{ "label": "PPLNS", "api_id": "dmd" }]
   }
   ```

   Its `api_id` is the pool's id in `https://example-pool.com/api/pools`. Without `modes`, the
   site takes every DMD pool its API lists.
2. Its logo in [mining-pool-logos](https://github.com/DebitMyData-PoW/mining-pool-logos), named as
   its slug (its name's lowercase letters and digits: `Example Pool` is `examplepool.svg`).

The site shows it within the hour. Pool operators can also ask from the site's "Add your pool"
window.

## Security

- **No keys, no coins**, and no node on the server.
- **Only Cloudflare reaches the web ports**; the only other open port is SSH.
- The service reads other sites only over **HTTPS, at public addresses**, with size and time
  limits and no redirect to another site. A pool's API answers are figures only: every value is
  checked, and the pages show them as text.
- **Nothing from GitHub runs on the server**: the lists must read as lists and each logo as a plain
  picture (no script, no link out); anything else is left out, and the last good one stays.
- The site runs only its own files: no other site's script, style, font or frame.

## Built with

Python (the service), nginx and SQLite on one small server; the site in plain HTML, CSS and
JavaScript, with ApexCharts for the charts.

## Installation

To run it on a server of your own, see **[INSTALL.md](INSTALL.md)**: what it needs, the install,
the settings, the commands, updates, troubleshooting and development.

## License

MIT. Fonts: SIL Open Font License (`web/fonts/OFL-Sora.txt`, `OFL-Inter.txt`,
`OFL-JetBrainsMono.txt`). ApexCharts: MIT (`web/vendor/LICENSE-apexcharts.txt`).
