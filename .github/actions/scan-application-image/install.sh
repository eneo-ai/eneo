#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$RUNNER_TEMP/eneo-image-scanners"
cd "$RUNNER_TEMP/eneo-image-scanners"
curl --fail --location --retry 3 --output trivy.tar.gz https://github.com/aquasecurity/trivy/releases/download/v0.75.0/trivy_0.75.0_Linux-64bit.tar.gz
echo 'c6e65abddb348e25f10549df887045629cf28cc72453cd1c63acb717316b3f3f  trivy.tar.gz' | sha256sum --check
tar -xzf trivy.tar.gz trivy
curl --fail --location --retry 3 --output grype.tar.gz https://github.com/anchore/grype/releases/download/v0.117.0/grype_0.117.0_linux_amd64.tar.gz
echo '38525dab1e06f162ebaa02f94d82d1f807076b011a44180cf2777edf1a7b9c26  grype.tar.gz' | sha256sum --check
tar -xzf grype.tar.gz grype
echo "$RUNNER_TEMP/eneo-image-scanners" >> "$GITHUB_PATH"
