# Vendored Swagger UI

This directory contains unmodified runtime assets from the official
[`swagger-ui-dist`](https://github.com/swagger-api/swagger-ui) npm package,
pinned to **5.35.0**. Eneo serves the bundle, stylesheet, and license notices
through an exact filename allowlist. `eneo-swagger-initializer.js` is Eneo's
local configuration, not an upstream asset. No npm installation or external
asset host is needed at runtime.

`upstream.json` records the exact registry metadata and tarball URLs, verified
npm SHA512 integrity, and SHA256/size of every vendored upstream file. Preserve
the Apache-2.0 `LICENSE`, upstream `NOTICE`, and the bundle's third-party
attributions in `swagger-ui-bundle.js.LICENSE.txt` with the assets.

## Updating

1. Check the stable version at
   `https://registry.npmjs.org/swagger-ui-dist/latest`, then select an exact
   version. Fetch its version-specific metadata at
   `https://registry.npmjs.org/swagger-ui-dist/<version>`. Check the package
   name, Apache-2.0 license, and `swagger-api/swagger-ui` repository.
2. Download that metadata's `dist.tarball`. Before opening the archive, require
   `base64.b64encode(hashlib.sha512(tarball_bytes).digest()).decode()` to equal
   the part after `sha512-` in `dist.integrity`. Reject other algorithms or a
   mismatch. Bound the download to 16 MiB and each retained file to 4 MiB;
   investigate upstream changes before increasing either limit.
3. Using Python's standard-library `tarfile`, read only these exact regular
   members with `extractfile`: `package/swagger-ui-bundle.js`,
   `package/swagger-ui.css`, `package/LICENSE`, `package/NOTICE`, and
   `package/swagger-ui-bundle.js.LICENSE.txt`. Require each exactly once.
   Write their bytes to the corresponding fixed filenames here; do not extract
   the whole archive, follow links, or use archive paths as output paths.
4. Replace `upstream.json` with the exact version, source URLs, integrity, and
   each retained file's SHA256 and byte size. Update the version above. Keep
   runtime files byte-for-byte upstream; review license changes and the diff.
5. Recompute all manifest hashes/sizes from disk, then run the focused API
   documentation tests, following the repository's local execution policy.
   Review that the documentation still uses the local assets and its existing
   Content Security Policy.

Run local download/extraction and verification commands through the global
supervisor, for example:

```sh
python3 /Users/maxeriksson/.codex/scripts/run-guarded.py --seconds 120 -- python3 /path/to/update-script.py
```

This procedure needs only Python's standard library. Do not add package-manager
dependencies, source maps, alternate bundles, or an automatic runtime update.
