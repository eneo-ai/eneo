/**
 * The pinned loader, `/widget/<version>/eneo.js`, is served as immutable and
 * printed with its SRI hash, so the bytes a version ships with may never
 * change: browsers and proxies keep the old ones for a year, and a host's
 * `integrity` blocks the new ones. release.json records the bytes the current
 * version ships with; every build compares its fresh bundle with it.
 */

const LOCK_COMMAND = "bun run --filter @eneo/widget-loader lock";

/**
 * @typedef {{ version: string; integrity: string }} Release
 */

/**
 * Why a build must stop, or null when the bundle is what release.json says.
 *
 * @param {Release} built
 * @param {Partial<Release> | null} locked
 * @returns {string | null}
 */
export function releaseProblem(built, locked) {
  if (!locked?.version || !locked.integrity) {
    return `release.json is missing or incomplete. Run \`${LOCK_COMMAND}\` and commit it.`;
  }
  if (locked.version === built.version && locked.integrity !== built.integrity) {
    return (
      `The loader's bytes changed but its version is still ${built.version}, whose pinned ` +
      `URL is immutable. Bump "version" in packages/widget-loader/package.json, then run ` +
      `\`${LOCK_COMMAND}\` and commit release.json.`
    );
  }
  if (locked.version !== built.version) {
    return (
      `package.json is at ${built.version} but release.json records ${locked.version}. ` +
      `Run \`${LOCK_COMMAND}\` and commit release.json.`
    );
  }
  return null;
}

/**
 * The floating channel, `/widget/<channel>/eneo.js`, that every default
 * snippet loads. It is not the semver major: it changes only with a bridge
 * protocol an installed page could misread, and changing it strands every
 * floating snippet already pasted into a site on the old address.
 *
 * @param {{ eneoWidgetChannel?: unknown }} pkg
 * @returns {string}
 */
export function loaderChannel(pkg) {
  const channel = pkg.eneoWidgetChannel;
  if (typeof channel !== "string" || !/^v\d+$/.test(channel)) {
    throw new Error(
      `packages/widget-loader/package.json needs "eneoWidgetChannel", the floating ` +
        `channel snippets load (for example "v1").`
    );
  }
  return channel;
}

/**
 * What `lock` writes for a new version. A version already recorded keeps its
 * bytes: changing them takes a new version, never a new lock.
 *
 * @param {Release} built
 * @param {Partial<Release> | null} locked
 * @returns {{ release: Release } | { refused: string }}
 */
export function lockRelease(built, locked) {
  if (
    locked?.version === built.version &&
    locked.integrity &&
    locked.integrity !== built.integrity
  ) {
    return {
      refused:
        `release.json already records other bytes for ${built.version}. ` +
        `Bump "version" in packages/widget-loader/package.json first.`
    };
  }
  return { release: { version: built.version, integrity: built.integrity } };
}
