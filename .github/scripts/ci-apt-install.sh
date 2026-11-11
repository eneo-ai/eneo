#!/usr/bin/env bash
# Install Ubuntu packages on a hosted runner: ci-apt-install.sh PACKAGE...
#
# A mirror whose throughput collapses kept downloads crawling for 315-1208 s
# (runs 40352666820, 40367572604, 41490522607), so only the network phase has
# a deadline: killing `apt-get update` or a --download-only install never
# touches dpkg, and the next attempt resumes the partial .debs. dpkg runs last,
# offline and without a deadline.
#
# Each attempt uses its own mirror: the runner's list, then archive.ubuntu.com,
# then mirrors.edge.kernel.org. In run 43049732281 neither azure.archive.ubuntu.com
# nor archive.ubuntu.com resolved, while kernel.org's mirror served the same
# packages that day (third attempt of eneo-mod-speech-to-text run 43053141729);
# a third mirror outside ubuntu.com lets CI pass such an outage. Every attempt fetches its mirror's index before downloading.
# `apt-get update` exits 0 when it fetched none ("ignored, or old ones used"),
# so its warning about the mirror list ends the attempt, and a download is
# never tried against the old index. Only the URI of the same Ubuntu archive
# changes: apt still verifies each Release file against Ubuntu's archive key,
# so a mirror over http cannot alter a package.
set -euo pipefail

(($#)) || exit 0
mirrors="${APT_MIRRORS:-/etc/apt/apt-mirrors.txt}"
fallbacks=(https://archive.ubuntu.com/ubuntu/ http://mirrors.edge.kernel.org/ubuntu/)

sudo tee /etc/apt/apt.conf.d/80-eneo-ci-network >/dev/null <<'APT'
Acquire::Retries "2";
Acquire::http::Timeout "30";
Acquire::https::Timeout "30";
APT

# Hosted runners read their Ubuntu sources through mirror+file:$mirrors.
use_mirror() {
  [[ -f "$mirrors" ]] || return 0
  printf '%s\tpriority:1\n' "$1" | sudo tee "$mirrors" >/dev/null
  echo "Switched apt to $1."
}

# Worst case: 3 x (60 + 180 + 2 x 15 s kill grace) = 13.5 min of network time.
fetch() {
  local limit=$1
  shift
  sudo timeout --kill-after=15s "$limit" apt-get -q "$@"
}

# Other sources (packages.microsoft.com) may fail without affecting our packages,
# so only the Ubuntu mirror list's warning counts.
fetch_index() {
  fetch 60s update 2>&1 | tee /dev/stderr | { ! grep 'Failed to fetch mirror+file:' >/dev/null; }
}

for attempt in 1 2 3; do
  ((attempt == 1)) || use_mirror "${fallbacks[attempt - 2]}"
  if fetch_index && fetch 180s install -y --no-install-recommends --download-only "$@"; then
    exec sudo apt-get install -y -q --no-install-recommends --no-download "$@"
  fi
  echo "::warning::apt-get could not fetch the packages (attempt $attempt/3)."
done
echo "::error::apt-get did not fetch the packages from any of three mirrors."
exit 1
