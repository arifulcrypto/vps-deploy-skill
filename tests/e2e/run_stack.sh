#!/usr/bin/env bash
# Full stack on one disposable machine: vps-lxc-skill creates containers, the deployer installs
# real 3X-UI over the forwarded SSH ports, and Mihomo sends traffic through the forwarded proxy ports.
# Needs root, an initialized LXD, sshpass, and MIHOMO pointing at a client binary.
# Usage: run_stack.sh <vps-lxc-skill checkout> <python with requirements> <work dir>
# Never prints result.json or client configs. The containers only exist for this job anyway.
set -euo pipefail
LXC_REPO="$1"; PY="$2"; WORK="$3"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LXC_OUT="$WORK/lxc"; DOMAIN=www.example.com; CDN=cdn.example.com
mkdir -p "$WORK"
HOST_IP="$(ip -4 route get 1.1.1.1 | sed -n 's/.* src \([0-9.]*\).*/\1/p')"
deployer() { "$PY" "$ROOT/scripts/vps_deployer.py" --from-lxc "$LXC_OUT/result.json" --no-online-sub "$@"; }

echo "::group::Provision containers"
time python3 "$LXC_REPO/scripts/vps_lxc.py" --local --count 2 --memory 1024 --disk 10 --output-dir "$LXC_OUT"
echo "::endgroup::"

echo "::group::Test certificate for the second container"
PKI="$WORK/pki"; mkdir -p "$PKI"
openssl ecparam -name prime256v1 -genkey -noout -out "$PKI/ca.key" 2>/dev/null
openssl req -new -x509 -key "$PKI/ca.key" -out "$PKI/ca.pem" -days 30 -subj '/CN=Stack Test CA' 2>/dev/null
openssl ecparam -name prime256v1 -genkey -noout -out "$PKI/leaf.key" 2>/dev/null
openssl req -new -key "$PKI/leaf.key" -out "$PKI/leaf.csr" -subj "/CN=$DOMAIN" 2>/dev/null
printf 'subjectAltName=DNS:%s,DNS:%s\n' "$DOMAIN" "$CDN" > "$PKI/san"
openssl x509 -req -in "$PKI/leaf.csr" -CA "$PKI/ca.pem" -CAkey "$PKI/ca.key" -CAcreateserial \
    -out "$PKI/leaf.pem" -days 30 -extfile "$PKI/san" 2>/dev/null
cat "$PKI/leaf.pem" "$PKI/ca.pem" > "$PKI/fullchain.pem"
lxc exec vps-02 -- mkdir -p "/root/cert/$DOMAIN"
lxc file push "$PKI/fullchain.pem" "vps-02/root/cert/$DOMAIN/fullchain.pem"
lxc file push "$PKI/leaf.key" "vps-02/root/cert/$DOMAIN/privkey.pem"
echo "::endgroup::"

echo "::group::Deploy IP-only profile to vps-01"
time deployer --container vps-01 --extra-protocols vmess --output-dir "$WORK/c1"
echo "::endgroup::"

echo "::group::Deploy single-port profile to vps-02"
# The token is never used: the valid test certificate makes the deployer skip issuance.
time CF_TOKEN=unused-token-for-the-stack-test-0000 deployer --container vps-02 --profile reality-self \
    --domain "$DOMAIN" --cdn-domain "$CDN" --output-dir "$WORK/c2"
echo "::endgroup::"

echo "Real client traffic"
"$PY" "$ROOT/tests/e2e/check_clients.py" "$WORK/c1/clash_config.yaml"
"$PY" "$ROOT/tests/e2e/check_clients.py" "$WORK/c2/clash_config.yaml" "$HOST_IP"

echo "Website behind the shared port"
curl -fsS -o /dev/null --max-time 10 --cacert "$PKI/ca.pem" --resolve "$DOMAIN:8443:$HOST_IP" "https://$DOMAIN:8443/"
if curl -sk -o /dev/null --max-time 10 --resolve "other.example.net:8443:$HOST_IP" "https://other.example.net:8443/"; then
    echo "unknown SNI must not get the website"; exit 1
fi

echo "Client traffic counters"
sleep 15
lxc file push "$ROOT/tests/e2e/traffic_counter.py" vps-01/root/traffic_counter.py
lxc exec vps-01 -- python3 /root/traffic_counter.py

echo "Built-in subscription"
"$PY" - "$WORK/c1/result.json" <<'PY'
import json, sys, urllib.request
sub = json.load(open(sys.argv[1]))["subscription"]
for url in (sub["url"], sub["clash_url"]):
    with urllib.request.urlopen(url, timeout=10) as res:
        assert res.status == 200 and res.read()
PY

echo "Redeploy keeps links"
cp "$WORK/c1/result.json" "$WORK/c1-first.json"
deployer --container vps-01 --extra-protocols vmess --output-dir "$WORK/c1" >/dev/null
"$PY" - "$WORK/c1-first.json" "$WORK/c1/result.json" <<'PY'
import json, sys
first, second = (json.load(open(path)) for path in sys.argv[1:3])
assert first["ports"] == second["ports"]
assert [n["uri"] for n in first["nodes"]] == [n["uri"] for n in second["nodes"]]
PY
echo "All stack checks passed"
