#!/usr/bin/env bash
# Install Ubuntu packages on a hosted runner: ci-apt-install.sh PACKAGE...
#
# A mirror whose throughput collapses kept downloads crawling for 315-1208 s
# (runs 40352666820, 40367572604, 41490522607), so only the network phase has
# a deadline: killing `apt-get update` or a --download-only install never
# touches dpkg, and the next attempt resumes the partial .debs. After the first
# failed attempt the runner's primary mirror, azure.archive.ubuntu.com, is
# dropped from its mirror list, so the retries use archive.ubuntu.com. dpkg
# runs last, offline and without a deadline.
set -euo pipefail

(($#)) || exit 0
mirrors="${APT_MIRRORS:-/etc/apt/apt-mirrors.txt}"

sudo tee /etc/apt/apt.conf.d/80-eneo-ci-network >/dev/null <<'APT'
Acquire::Retries "2";
Acquire::http::Timeout "30";
Acquire::https::Timeout "30";
APT

fetch() {
  for attempt in 1 2 3; do
    if sudo timeout --kill-after=15s 240s apt-get -q "$@"; then
      return 0
    fi
    echo "::warning::apt-get $1 failed or exceeded 240 s (attempt $attempt/3)."
    if grep -qs azure.archive.ubuntu.com "$mirrors"; then
      sudo sed -i '/azure\.archive\.ubuntu\.com/d' "$mirrors"
      echo "Switched apt to $(head -n1 "$mirrors" | cut -f1)."
    fi
  done
  echo "::error::apt-get $1 did not finish in three bounded attempts."
  return 1
}

fetch update
fetch install -y --no-install-recommends --download-only "$@"
sudo apt-get install -y -q --no-install-recommends --no-download "$@"
