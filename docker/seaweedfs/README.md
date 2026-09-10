# Eneo SeaweedFS image

Eneo builds `ghcr.io/eneo-ai/eneo-seaweedfs` from a pinned upstream source
archive plus one hashed downstream patch. `.github/workflows/seaweedfs_image.yml`
owns the build, verification, and publication; `verify-supply-chain.sh` owns the
source and image policy; `smoke-reference-deployment.sh` proves the reference
Compose bootstrap and volume persistence.

Every input is pinned, so the image is reproducible and is rebuilt only when a
file in this directory, the workflow, or the reference Compose files change on
`develop`. The published tag is the contents of `VERSION`, published once and
never moved. Operators still pin the manifest digest from a release's
`IMAGE-DIGESTS.txt`.

## When the weekly re-audit goes red

The scheduled run repeats `govulncheck` on the pinned source and Grype on both
published platform digests. A new advisory in a reachable dependency fails it.
Clear it by upgrading the dependency in the downstream patch:

1. Download the pinned archive, extract it, and `git apply` the current patch
   on top (create a throwaway git repository first so `git diff` works).
2. In the builder image named by `GO_IMAGE` in `verify-supply-chain.sh`, run
   `go get <module>@<fixed version>` at the repository root. If the fixed
   version needs a newer Go, move `GO_IMAGE` and the Dockerfile `FROM` line to
   the current patch release of that Go minor (pin the multi-platform digest
   from Docker Hub) and let `go get` raise the `go` directive.
3. Regenerate the patch as `git diff` from the pristine archive with the
   `Subject:` header updated, and confirm `git apply --check` succeeds against
   the pristine source.
4. Update `DOWNSTREAM_PATCH_SHA256` in `verify-supply-chain.sh` and both
   occurrences in the `Dockerfile`, and add the new module version to the
   `modules.json` assertion in `audit_source`.
5. Bump `VERSION`.
6. Validate locally in the same builder image: `govulncheck -show=traces ./...`
   from `weed/` reports zero reachable vulnerabilities and `go-licenses` still
   reports the same `Unknown` package set. Then build the image the way the
   workflow does:

   ```bash
   docker buildx build docker/seaweedfs \
     --build-arg SOURCE_DATE_EPOCH=1784519823 \
     --build-arg IMAGE_VERSION="$(cat docker/seaweedfs/VERSION)"
   ```

Open a pull request; it runs the source policy plus the full build, smoke
test, SBOM, and vulnerability gate against a local registry with read-only
permissions. Merging to `develop` repeats that against GHCR, attests, and
publishes the new version.

## When upstream ships the fix

Move the source pin instead of growing the patch: update `SOURCE_COMMIT`,
`SOURCE_TREE`, `SOURCE_ARCHIVE_SHA256`, and `SOURCE_LICENSE_SHA256` in
`verify-supply-chain.sh`, the matching `ADD --checksum` URL and labels in the
`Dockerfile`, drop or shrink the patch, then follow the steps above.
