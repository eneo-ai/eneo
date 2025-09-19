#!/bin/bash

set -e

VERSION="$1"

if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 <version>"
    exit 1
fi

echo "{\".\": \"$VERSION\"}" > backend/.release-please-manifest.json
echo "Created backend/.release-please-manifest.json with version: $VERSION"