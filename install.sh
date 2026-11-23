#!/usr/bin/env bash
# DMD Mining (mining.debitmydata.io): installs everything, or updates it when run again.
#
#   sudo /opt/debitmydata-mining/install.sh
#
# Before the first run (README, "Install"): a fresh Ubuntu 24.04 server; this repository at
# /opt/debitmydata-mining; the Cloudflare origin certificate in /etc/ssl/cloudflare/.
#
# What it sets up:
#   dmd-mining.service    the service (mining/): the pools' APIs every minute, the blocks from DMD
#                         Stats every 20 seconds, the pool list from GitHub every hour, the
#                         notifications, and the site's files
#   nginx                 the site (web/), behind Cloudflare
#   ufw                   SSH, and ports 80 and 443 for Cloudflare only
#   a swap file           on a server with less than 2 GB of memory
#
# No DebitMyData node: who found each block comes from DMD Stats (stats.debitmydata.io), which has
# its own. It keeps the settings, the database (every block, the pools' history, the devices with
# notifications on) and the notifications' key.
set -euo pipefail
trap 'printf "\nERROR: the install stopped at line %s: %s\nRun it again once that is fixed: it carries on with what is already done.\n" "$LINENO" "$BASH_COMMAND" >&2' ERR

APP=/opt/debitmydata-mining
CONF=/etc/dmd-mining
ENV_FILE=$CONF/mining.env
INSTALL_CONF=$CONF/install.conf
DATA=/var/lib/dmd-mining
VENV=$APP/.venv
WEB=/var/www/dmd-mining

step() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
setting() { grep -E "^$1=" "$INSTALL_CONF" 2>/dev/null | tail -1 | cut -d= -f2- || true; }
ask() {  # ask NAME "question" default: the answer kept in install.conf, asked only once
    local name="$1" question="$2" default="$3" value
    value="$(setting "$name")"
    if [ -z "$value" ]; then
        if [ -t 0 ]; then
            read -r -p "$question [$default]: " value
        fi
        value="${value:-$default}"
        echo "$name=$value" >>"$INSTALL_CONF"
    fi
    printf -v "$name" '%s' "$value"
}

# ------------------------------------------------------------------ checks
step "Checking"
[ "$(id -u)" -eq 0 ] || fail "run as root: sudo $0"
grep -q 'VERSION_ID="24.04"' /etc/os-release || fail "this script is for Ubuntu 24.04"
[ "$(cd "$(dirname "$0")" && pwd)" = "$APP" ] || fail "the repository must be at $APP (git clone ... $APP)"
install -d -m 750 "$CONF"
touch "$INSTALL_CONF"
chmod 600 "$INSTALL_CONF"

ask MINING_HOST "The site's address" "mining.debitmydata.io"
ask CERT_NAME "The Cloudflare origin certificate's name in /etc/ssl/cloudflare/" "debitmydata.io"
CERT=/etc/ssl/cloudflare/$CERT_NAME.pem
CERT_KEY=/etc/ssl/cloudflare/$CERT_NAME.key
[ -s "$CERT" ] && [ -s "$CERT_KEY" ] ||
    fail "the Cloudflare origin certificate is missing: save it as $CERT and its private key as $CERT_KEY (README, step 2)"
openssl x509 -in "$CERT" -noout -checkhost "$MINING_HOST" | grep -q "does match" ||
    fail "$CERT does not cover $MINING_HOST: make one for *.$(echo "$MINING_HOST" | cut -d. -f2-) in Cloudflare"
chmod 644 "$CERT"
chmod 600 "$CERT_KEY"

# ------------------------------------------------------------------ packages, and memory
step "Installing packages"
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1
apt-get update -q
apt-get install -y -q --no-install-recommends nginx python3-venv ufw curl librsvg2-bin unattended-upgrades >/dev/null
# (A 1 GB server: a swap file, so that an update's pip install never runs out of memory.)
if [ "$(awk '/MemTotal/ {print $2}' /proc/meminfo)" -lt 2000000 ] && ! swapon --show | grep -q .; then
    step "A 1 GB swap file"
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
    echo 'vm.swappiness=10' >/etc/sysctl.d/90-dmd-mining-swap.conf
    sysctl -q -p /etc/sysctl.d/90-dmd-mining-swap.conf
fi

# ------------------------------------------------------------------ the service
step "The service"
id dmdmining >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin dmdmining
install -d -m 755 -o dmdmining -g dmdmining "$DATA" "$DATA/public"
install -d -m 700 -o dmdmining -g dmdmining "$DATA/push"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip >/dev/null
"$VENV/bin/pip" install -q --upgrade "$APP/mining" >/dev/null
"$VENV/bin/pip" install -q --force-reinstall --no-deps "$APP/mining" >/dev/null
if [ ! -s "$ENV_FILE" ]; then
    cat >"$ENV_FILE" <<EOF
# DMD Mining's settings (README, "Settings"). After a change: sudo systemctl restart dmd-mining
DMDM_SITE_URL=https://$MINING_HOST
DMDM_STATS_URL=https://stats.debitmydata.io
DMDM_POOLS_URL=https://raw.githubusercontent.com/DebitMyData-PoW/mining-pools/master
DMDM_LOGOS_URL=https://raw.githubusercontent.com/DebitMyData-PoW/mining-pool-logos/master
DMDM_EXPLORER_URL=https://mempool.debitmydata.io
DMDM_DATA_DIR=$DATA
DMDM_POLL_SECONDS=60
DMDM_CHAIN_SECONDS=20
DMDM_CATALOG_SECONDS=3600
DMDM_PUSH_LISTEN=127.0.0.1:8481
DMDM_PUSH_SUBJECT=mailto:info@debitmydata.com
DMDM_PUSH_MAX_DEVICES=20000
EOF
fi
add_setting() {  # add_setting NAME value "comment": a setting a newer version added
    grep -qE "^#? ?$1=" "$ENV_FILE" || printf '\n# %s\n%s=%s\n' "$3" "$1" "$2" >>"$ENV_FILE"
}
chown root:dmdmining "$ENV_FILE"
chmod 640 "$ENV_FILE"
cat >/usr/local/sbin/dmd-mining-admin <<'EOF'
exec systemd-run --quiet --pipe --wait --collect --uid=dmdmining --gid=dmdmining \
    -p EnvironmentFile=/etc/dmd-mining/mining.env \
    /opt/debitmydata-mining/.venv/bin/dmd-mining "$@"
EOF
chmod 755 /usr/local/sbin/dmd-mining-admin
dmd-mining-admin push-keys >/dev/null
install -m 644 "$APP/config/systemd/dmd-mining.service" /etc/systemd/system/dmd-mining.service
systemctl daemon-reload
systemctl enable dmd-mining >/dev/null
systemctl restart dmd-mining

# ------------------------------------------------------------------ the site
step "The site and nginx"
install -d -m 755 "$WEB"
rm -rf "${WEB:?}"/*
cp -r "$APP/web/." "$WEB/"
find "$WEB" -type d -exec chmod 755 {} + && find "$WEB" -type f -exec chmod 644 {} +
install -m 644 "$APP/config/nginx/headers.conf" /etc/nginx/snippets/dmd-mining-headers.conf
install -m 644 "$APP/config/nginx/csp.conf" /etc/nginx/snippets/dmd-mining-csp.conf
sed -e "s#@HOST@#$MINING_HOST#g" -e "s#@CERT@#$CERT#g" -e "s#@KEY@#$CERT_KEY#g" \
    "$APP/config/nginx/site.conf.template" >/etc/nginx/sites-available/dmd-mining
if [ ! -e /proc/net/if_inet6 ]; then
    sed -i '/listen \[::\]/d' /etc/nginx/sites-available/dmd-mining
fi
ln -sf /etc/nginx/sites-available/dmd-mining /etc/nginx/sites-enabled/dmd-mining
rm -f /etc/nginx/sites-enabled/default
nginx -t -q
systemctl enable nginx >/dev/null
systemctl reload nginx || systemctl restart nginx

# ------------------------------------------------------------------ the firewall
step "The firewall"
SSH_PORT="${SSH_CONNECTION##* }"
if ! [[ "$SSH_PORT" =~ ^[0-9]+$ ]]; then
    SSH_PORT="$( (sshd -T 2>/dev/null || true) | awk '/^port /{print $2; exit}')"
fi
ufw allow "${SSH_PORT:-22}/tcp" comment 'SSH' >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw --force enable >/dev/null
"$APP/cloudflare.sh"

# ------------------------------------------------------------------ done
step "Checking"
for unit in dmd-mining nginx; do
    printf '  %-12s %s\n' "$unit" "$(systemctl is-active "$unit" || true)"
done
sleep 5
dmd-mining-admin status || true
cat <<EOF

DMD Mining is installed: https://$MINING_HOST
The first time, it reads every block from DMD Stats and the pool list from GitHub: the site
fills within a minute or two. Its pools' charts fill as it follows them, minute by minute.

  sudo dmd-mining-admin status      what it knows
  journalctl -u dmd-mining -f       its log

Keep $DATA/push/vapid.pem in your backups: a new key means every device has to turn
notifications on again.
EOF
