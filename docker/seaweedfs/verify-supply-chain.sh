#!/usr/bin/env bash

set -euo pipefail

readonly SOURCE_COMMIT="875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa"
readonly SOURCE_TREE="f6590c71c41ec414fc193b89e9d9dd586d39ad17"
readonly SOURCE_ARCHIVE_SHA256="2e37f5d8980256e490324e3759d38437ecfee734f60aa3e75528b05f7d19460e"
readonly SOURCE_LICENSE_SHA256="d789d433cc11da163273d1e39be2e8fa67642f9a58ef220d3f258fa9c14ef613"
readonly DOWNSTREAM_PATCH_NAME="0001-upgrade-grpc-to-1.82.1.patch"
readonly DOWNSTREAM_PATCH_SHA256="54cc9bd8b0cfadebbce56754914655526cee882075141fd64790686bd4ac409e"
readonly SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly DOWNSTREAM_PATCH="$SCRIPT_DIRECTORY/patches/$DOWNSTREAM_PATCH_NAME"
readonly GO_IMAGE="docker.io/library/golang:1.25.12-bookworm@sha256:ea341baa9bd5ba6784f6d7161ace70544349a6242d54d34a0fbfd2c4d51c9d58"
readonly GO_LICENSES_REVISION="3e084b0caf710f7bfead967567539214f598c0a2"
readonly GOVULNCHECK_VERSION="v1.6.0"

usage() {
    cat >&2 <<EOF
usage:
  $0 source OUTPUT_DIRECTORY
  SYFT_CMD=/path/to/syft $0 image IMAGE_REF PLATFORM OUTPUT_DIRECTORY
EOF
    exit 2
}

require_command() {
    command -v "$1" >/dev/null || {
        echo "required command is unavailable: $1" >&2
        exit 1
    }
}

verify_known_license() {
    local url="$1"
    local expected_sha256="$2"
    local destination="$3"

    curl --fail --location --silent --show-error "$url" --output "$destination"
    printf '%s  %s\n' "$expected_sha256" "$destination" \
        | sha256sum --check --strict -
}

audit_source() {
    [[ $# -eq 1 ]] || usage
    local output_directory="$1"
    local work_directory
    local source_directory
    local upstream_tree

    for command in curl diff docker git jq sha256sum tar; do
        require_command "$command"
    done

    work_directory="$(mktemp -d)"
    source_directory="$work_directory/source"
    trap 'rm -rf "$work_directory"' RETURN
    mkdir -p "$source_directory" "$output_directory"
    output_directory="$(cd "$output_directory" && pwd -P)"

    curl --fail --location --silent --show-error \
        "https://github.com/seaweedfs/seaweedfs/archive/${SOURCE_COMMIT}.tar.gz" \
        --output "$work_directory/seaweedfs.tar.gz"
    printf '%s  %s\n' "$SOURCE_ARCHIVE_SHA256" "$work_directory/seaweedfs.tar.gz" \
        | sha256sum --check --strict -
    tar --extract --gzip --file="$work_directory/seaweedfs.tar.gz" \
        --strip-components=1 --directory="$source_directory"
    printf '%s  %s\n' "$SOURCE_LICENSE_SHA256" "$source_directory/LICENSE" \
        | sha256sum --check --strict -

    upstream_tree="$(
        curl --fail --location --silent --show-error \
            --proto '=https' --tlsv1.2 \
            "https://api.github.com/repos/seaweedfs/seaweedfs/git/commits/${SOURCE_COMMIT}" \
            | jq -er --arg commit "$SOURCE_COMMIT" '
                select(.sha == $commit) | .tree.sha
            '
    )"
    [[ "$upstream_tree" == "$SOURCE_TREE" ]] || {
        echo "upstream source tree does not match the pinned commit" >&2
        exit 1
    }

    printf '%s  %s\n' "$DOWNSTREAM_PATCH_SHA256" "$DOWNSTREAM_PATCH" \
        | sha256sum --check --strict -
    git -C "$source_directory" apply --check "$DOWNSTREAM_PATCH"
    git -C "$source_directory" apply "$DOWNSTREAM_PATCH"
    cp "$DOWNSTREAM_PATCH" "$output_directory/$DOWNSTREAM_PATCH_NAME"

    docker run --rm \
        --volume "$source_directory:/src:ro" \
        --volume "$output_directory:/out" \
        --entrypoint /bin/bash \
        "$GO_IMAGE" \
        -c "set -euo pipefail
            export GOBIN=/tmp/bin
            go install github.com/google/go-licenses/v2@${GO_LICENSES_REVISION}
            go install golang.org/x/vuln/cmd/govulncheck@${GOVULNCHECK_VERSION}
            cd /src
            /tmp/bin/go-licenses report ./... >/out/licenses.csv 2>/out/licenses.stderr
            go list -mod=readonly -m -json all >/out/modules.json
            cd /src/weed
            /tmp/bin/govulncheck -show=traces ./... | tee /out/govulncheck.txt"

    jq -s -e '
        any(.[]; .Path == "github.com/google/flatbuffers/go"
            and .Version == "v0.0.0-20230108230133-3b8644d32c50")
        and any(.[]; .Path == "github.com/jmespath/go-jmespath"
            and .Version == "v0.4.0")
        and any(.[]; .Path == "github.com/kurin/blazer"
            and .Version == "v0.5.3")
        and any(.[]; .Path == "github.com/apache/thrift"
            and .Version == "v0.23.0"
            and .Replace.Path == "github.com/apache/thrift"
            and .Replace.Version == "v0.23.1-0.20260429145742-d2acd3c49e58")
        and any(.[]; .Path == "google.golang.org/grpc"
            and .Version == "v1.82.1")
        ' "$output_directory/modules.json" >/dev/null

    cut -d, -f3 "$output_directory/licenses.csv" | LC_ALL=C sort -u \
        | while IFS= read -r license; do
            case "$license" in
                Apache-2.0 | BSD-2-Clause | BSD-3-Clause \
                    | GNU-All-permissive-Copying-License | ISC | MIT | MPL-2.0 \
                    | Unknown)
                    ;;
                *)
                    echo "disallowed dependency license: $license" >&2
                    exit 1
                    ;;
            esac
        done

    awk -F, '$3 == "Unknown" { print $1 }' "$output_directory/licenses.csv" \
        | LC_ALL=C sort -u >"$work_directory/unknown-packages.actual"
    cat >"$work_directory/unknown-packages.expected" <<'EOF'
github.com/google/flatbuffers/go
github.com/jmespath/go-jmespath
github.com/kurin/blazer/b2
github.com/kurin/blazer/base
github.com/kurin/blazer/internal/b2assets
github.com/kurin/blazer/internal/b2types
github.com/kurin/blazer/internal/blog
github.com/kurin/blazer/x/window
EOF
    diff --unified "$work_directory/unknown-packages.expected" \
        "$work_directory/unknown-packages.actual"

    # These exact license files resolve classifier false negatives. Version or
    # content drift fails above or here; this is not a vulnerability waiver.
    verify_known_license \
        "https://raw.githubusercontent.com/google/flatbuffers/3b8644d32c50/LICENSE.txt" \
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30" \
        "$work_directory/flatbuffers.LICENSE"
    verify_known_license \
        "https://raw.githubusercontent.com/jmespath/go-jmespath/v0.4.0/LICENSE" \
        "03cfaf331a260694d06227a589cdd2b5fcfab474697b72e250736696c313655a" \
        "$work_directory/jmespath.LICENSE"
    verify_known_license \
        "https://raw.githubusercontent.com/kurin/blazer/v0.5.3/LICENSE" \
        "e2851ee2c9388d5f19a5bed780dfdc16ec860909545b092a399d4ef73a81b7f7" \
        "$work_directory/blazer.LICENSE"
    verify_known_license \
        "https://raw.githubusercontent.com/apache/thrift/d2acd3c49e58/LICENSE" \
        "89aa7b27868669299bd8a6c53b72ec4beadce42dad6c8336797cc26e1e8df98d" \
        "$work_directory/thrift.LICENSE"

    grep -Fqx "Your code is affected by 0 vulnerabilities." \
        "$output_directory/govulncheck.txt"

    cat >"$output_directory/SOURCE-PROVENANCE.txt" <<EOF
upstream=SeaweedFS 4.40
source_commit=$SOURCE_COMMIT
source_tree=$SOURCE_TREE
source_archive_sha256=$SOURCE_ARCHIVE_SHA256
source_license=Apache-2.0
downstream_patch=$DOWNSTREAM_PATCH_NAME
downstream_patch_sha256=$DOWNSTREAM_PATCH_SHA256
builder=$GO_IMAGE
go_licenses_revision=$GO_LICENSES_REVISION
govulncheck_version=$GOVULNCHECK_VERSION
EOF
    (
        cd "$output_directory"
        sha256sum -- SOURCE-PROVENANCE.txt "$DOWNSTREAM_PATCH_NAME" \
            govulncheck.txt licenses.csv modules.json \
            >SOURCE-SHA256SUMS
    )
}

audit_image() {
    [[ $# -eq 3 ]] || usage
    local image_ref="$1"
    local platform="$2"
    local output_directory="$3"
    local platform_slug="${platform//\//-}"
    local cyclonedx_file="$output_directory/seaweedfs-${platform_slug}.cyclonedx.json"
    local spdx_file="$output_directory/seaweedfs-${platform_slug}.spdx.json"
    local provenance_file="$output_directory/IMAGE-PROVENANCE-${platform_slug}.txt"

    for command in docker jq sha256sum; do
        require_command "$command"
    done
    [[ -n "${SYFT_CMD:-}" && -x "$SYFT_CMD" ]] || {
        echo "SYFT_CMD must name an executable Syft binary" >&2
        exit 1
    }
    mkdir -p "$output_directory"

    if ! docker image inspect "$image_ref" >/dev/null 2>&1; then
        docker pull --platform "$platform" "$image_ref" >/dev/null
    fi
    docker image inspect "$image_ref" | jq -e \
        --arg commit "$SOURCE_COMMIT" \
        --arg tree "$SOURCE_TREE" \
        --arg archive "$SOURCE_ARCHIVE_SHA256" \
        --arg patch "$DOWNSTREAM_PATCH_SHA256" '
        length == 1
        and .[0].Config.User == "65532:65532"
        and .[0].Config.WorkingDir == "/data"
        and .[0].Config.Entrypoint == ["/usr/local/bin/weed"]
        and .[0].Config.Cmd == ["version"]
        and ((.[0].Config.ExposedPorts | keys) == ["8333/tcp"])
        and .[0].Config.Labels["org.opencontainers.image.vendor"] == "Eneo"
        and .[0].Config.Labels["org.opencontainers.image.licenses"] == "Apache-2.0"
        and .[0].Config.Labels["io.eneo.upstream.commit"] == $commit
        and .[0].Config.Labels["io.eneo.upstream.tree"] == $tree
        and .[0].Config.Labels["io.eneo.upstream.archive.sha256"] == $archive
        and .[0].Config.Labels["io.eneo.downstream.patch.sha256"] == $patch
        ' >/dev/null

    "$SYFT_CMD" "docker:$image_ref" --platform "$platform" --quiet \
        --output "cyclonedx-json=$cyclonedx_file" \
        --output "spdx-json=$spdx_file"
    jq -e '
        .bomFormat == "CycloneDX"
        and .specVersion == "1.6"
        and ((.components // []) | length > 0)
        ' "$cyclonedx_file" >/dev/null
    jq -e '
        .spdxVersion == "SPDX-2.3"
        and ((.packages // []) | length > 0)
        ' "$spdx_file" >/dev/null

    cat >"$provenance_file" <<EOF
image=$image_ref
platform=$platform
source_commit=$SOURCE_COMMIT
source_tree=$SOURCE_TREE
source_archive_sha256=$SOURCE_ARCHIVE_SHA256
EOF
    (
        cd "$output_directory"
        sha256sum -- \
            "$(basename "$cyclonedx_file")" \
            "$(basename "$spdx_file")" \
            "$(basename "$provenance_file")" \
            >"IMAGE-SHA256SUMS-${platform_slug}"
    )
}

mode="${1:-}"
case "$mode" in
    source)
        shift
        audit_source "$@"
        ;;
    image)
        shift
        audit_image "$@"
        ;;
    *)
        usage
        ;;
esac
