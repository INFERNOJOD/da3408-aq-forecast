#!/usr/bin/env bash
# Make a local certificate authority and one server certificate for TLS.
#
#   scripts/make_certs.sh [extra-host-or-ip ...]
#
# Writes certs/ (gitignored; CERT_DIR overrides it, which the tests use):
# ca.crt, ca.key, server.crt, server.key.
# The server certificate is valid for localhost, 127.0.0.1 and the compose
# service names (backend, frontend), plus any extra names or IPs given, for
# example the VM's address so a phone on the same network can open the page.
#
# I sign the server certificate with my own small CA instead of making one
# bare self-signed certificate. The CA is still self-made, but the services
# can then check the backend's certificate against ca.crt (no verify=False
# anywhere), and a browser that imports ca.crt once stops showing a warning.
# Run it again to replace the certificates; existing files are overwritten.
set -euo pipefail

cd "$(dirname "$0")/.."
out="${CERT_DIR:-certs}"
days=825                       # the longest validity browsers accept
mkdir -p "$out"
chmod 700 "$out"

san="DNS:localhost,DNS:backend,DNS:frontend,IP:127.0.0.1"
for extra in "$@"; do
    if [[ "$extra" =~ ^[0-9.]+$ ]]; then
        san="$san,IP:$extra"
    else
        san="$san,DNS:$extra"
    fi
done

openssl req -x509 -newkey rsa:2048 -nodes -days "$days" \
    -keyout "$out/ca.key" -out "$out/ca.crt" \
    -subj "/CN=AQ Forecast local CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null

openssl req -newkey rsa:2048 -nodes \
    -keyout "$out/server.key" -out "$out/server.csr" \
    -subj "/CN=localhost" 2>/dev/null

openssl x509 -req -in "$out/server.csr" -days "$days" \
    -CA "$out/ca.crt" -CAkey "$out/ca.key" -CAcreateserial \
    -out "$out/server.crt" \
    -extfile <(printf "subjectAltName=%s\nextendedKeyUsage=serverAuth\n" "$san") \
    2>/dev/null

rm -f "$out/server.csr" "$out/ca.srl"
chmod 600 "$out"/*.key
chmod 644 "$out"/*.crt
echo "Wrote $out/ca.crt and $out/server.crt for: $san"
