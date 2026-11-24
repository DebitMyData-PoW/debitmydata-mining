# Installing DMD Mining

These steps install the site on a server of your own: the service that follows the pools and the
chain, its notifications, and the website behind nginx. Below, `example.com` and
`mining.example.com` stand for your own domain and name.

## What you need

- **A small Ubuntu 24.04 server** (x86_64): 1 vCPU and 1 GB of memory are enough (the install adds
  a 1 GB swap file), 25 GB of disk, at any provider. Best in another data centre than the pools it
  watches. Root access with an SSH key.
- **A DMD Stats page, version 1.1.12 or later**: the public page of the
  [DebitMyData monitor](https://github.com/DebitMyData-PoW/debitmydata-monitor), your own or the
  DebitMyData network's public one. It publishes `blocks.json`, the blocks this site follows
  (`DMDM_STATS_URL`, below). The site needs no node of its own.
- **A name** for the site (for example `mining.example.com`), as a DNS record in **Cloudflare**,
  **proxied** (the orange cloud): the install lets only Cloudflare reach the web ports.
- **A Cloudflare origin certificate** for that name: in Cloudflare, your domain, **SSL/TLS**,
  **Origin Server**, **Create Certificate** (RSA, 15 years). The names Cloudflare suggests,
  `example.com` and `*.example.com`, cover it. In **SSL/TLS**, **Overview**, set the encryption
  mode to **Full (strict)**.

## Install

1. **The server.** Log in as root with your key, then turn off password logins and update it:

   ```
   printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' > /etc/ssh/sshd_config.d/00-keys-only.conf
   sshd -t && systemctl reload ssh
   apt-get update && apt-get -y upgrade && apt-get -y install git
   ```

2. **The certificate.** Paste the origin certificate, then its private key (in nano: Ctrl+O,
   Enter, Ctrl+X to save). Name both files after your domain:

   ```
   mkdir -p /etc/ssl/cloudflare
   nano /etc/ssl/cloudflare/example.com.pem
   nano /etc/ssl/cloudflare/example.com.key
   chmod 600 /etc/ssl/cloudflare/example.com.key
   ```

3. **This repository, and the install** (a few minutes):

   ```
   git clone https://github.com/DebitMyData-PoW/debitmydata-mining.git /opt/debitmydata-mining
   /opt/debitmydata-mining/install.sh
   ```

   It asks two questions: the site's name (`mining.example.com`) and the certificate's name from
   step 2 (`example.com`). Type your own: Enter keeps the answer in brackets. At the end it prints
   what the service knows.

4. **The settings.** The sources start on the DebitMyData network's public ones. To use your own
   DMD Stats page or explorer, and to give the browsers' push services your own contact, change
   them (the table below), then restart:

   ```
   nano /etc/dmd-mining/mining.env
   systemctl restart dmd-mining
   ```

5. **Check.** `https://mining.example.com` shows the pools within a minute or two (the first time,
   it reads every block from DMD Stats). The pools' charts fill as the service follows them,
   minute by minute: a pool's 24-hour chart is full after a day.

## Commands

| Command | |
| :-- | :-- |
| `sudo dmd-mining-admin status` | The blocks it knows, when it last read the chain and the pools, each pool's API, the devices with notifications on |
| `sudo dmd-mining-admin pools` | Reads the pool list and the logos from GitHub now (else every hour) |
| `sudo dmd-mining-admin publish` | Writes the site's files now |
| `sudo dmd-mining-admin push-keys` | Shows the notifications' public key (makes the key if there is none) |
| `journalctl -u dmd-mining -f` | The service's log |
| `systemctl status dmd-mining nginx` | The services |

## Settings

`/etc/dmd-mining/mining.env` (after a change: `sudo systemctl restart dmd-mining`):

| Setting | Default | |
| :-- | :-- | :-- |
| `DMDM_SITE_URL` | `https://` + the site's name | The site (only its pages may change notifications) |
| `DMDM_STATS_URL` | the DebitMyData network's DMD Stats | Where the blocks come from |
| `DMDM_POOLS_URL` | `https://raw.githubusercontent.com/DebitMyData-PoW/mining-pools/master` | `pools-v2.json` and `pools-info.json` |
| `DMDM_LOGOS_URL` | `https://raw.githubusercontent.com/DebitMyData-PoW/mining-pool-logos/master` | The logos |
| `DMDM_EXPLORER_URL` | the DebitMyData network's mempool explorer | Where blocks and addresses link to |
| `DMDM_POLL_SECONDS` | `60` | Between two reads of the pools' APIs (30 at least) |
| `DMDM_CHAIN_SECONDS` | `20` | Between two reads of DMD Stats' blocks |
| `DMDM_CATALOG_SECONDS` | `3600` | Between two reads of the pool list |
| `DMDM_PUSH_SUBJECT` | DebitMyData's contact | `mailto:` your own address, given to the browsers' push services as they ask |
| `DMDM_PUSH_MAX_DEVICES` | `20000` | Devices with notifications on, at most |

**The notifications' key** (`/var/lib/dmd-mining/push/vapid.pem`, made by the install) belongs in
your backups: a new key means every device has to turn notifications on again.

## Your own site

The site's name, text and images (`web/`) and its app manifest (`web/manifest.json`) are
DebitMyData's: change them for a site of your own, then update the server (below). The app's icons
are the DMD coin with a flame in a red badge; `tools/make-app-icons.py` makes them again.

**The app on Google Play** (optional). The site installs as an app from the browser. If you also
publish it on Google Play (a Bubblewrap app, with a package name like `com.example.mining`), add
`{ "platform": "play", "id": "com.example.mining" }` to `related_applications` in
`web/manifest.json`, and `web/.well-known/assetlinks.json` with the package name and the Play app
signing key's SHA-256 fingerprint (Play Console, App integrity), as Bubblewrap explains.

## Updating

```
cd /opt/debitmydata-mining && git pull && ./install.sh
```

It keeps the settings, the database and the notifications' key.

## If something is wrong

- **The blocks don't move** (`dmd-mining-admin status`: "Chain read from DMD Stats" long ago, and
  "blocks.json: HTTP 404" in the log): the DMD Stats page is older than 1.1.12. Update it.
- **"HTTP 403" from DMD Stats or a pool in the log**: Cloudflare's bot protection may be stopping
  this server. In Cloudflare, the domain of the site that refuses, **Security**, **WAF**, add a
  custom rule that skips the bot checks for this server's IP address.
- **A pool shows "Not answering"** while its site works: its API's address in `pools-info.json` may
  have changed. `dmd-mining-admin status` shows the error.

## Development

```
cd mining
python3 -m venv .venv && .venv/bin/pip install -e '.[test]' ruff
.venv/bin/pytest
.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests
```

The tests run the service against stand-ins for DMD Stats, GitHub and the pools' APIs
(`tests/conftest.py`).
