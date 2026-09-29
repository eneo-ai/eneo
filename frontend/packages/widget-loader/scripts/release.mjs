/**
 * Pinned loader URLs are immutable. release.json keeps every version's script
 * and stylesheet hashes, including archived versions, so a changed asset and
 * manifest cannot silently rewrite an old release.
 */

const LOCK_COMMAND = "bun run --filter @eneo/widget-loader lock";

/**
 * @typedef {{ version: string; integrity: string; css_integrity?: string }} Release
 * @typedef {{ releases: Release[] }} ReleaseRegistry
 */

/** @param {Release} a @param {Release} b */
function sameBytes(a, b) {
  return a.integrity === b.integrity && a.css_integrity === b.css_integrity;
}

/**
 * Why a build must stop, or null when the current bytes match the latest lock.
 *
 * @param {Release} built
 * @param {ReleaseRegistry | null} locked
 * @returns {string | null}
 */
export function releaseProblem(built, locked) {
  const latest = locked?.releases?.at(-1);
  if (!latest?.version || !latest.integrity) {
    return `release.json is missing or incomplete. Run \`${LOCK_COMMAND}\` and commit it.`;
  }
  if (latest.version !== built.version) {
    return (
      `package.json is at ${built.version} but release.json records ${latest.version}. ` +
      `Run \`${LOCK_COMMAND}\` and commit release.json.`
    );
  }
  if (!sameBytes(latest, built)) {
    return (
      `The loader's bytes changed but its version is still ${built.version}, whose pinned ` +
      `URL is immutable. Bump "version" in packages/widget-loader/package.json, then run ` +
      `\`${LOCK_COMMAND}\` and commit release.json.`
    );
  }
  return null;
}

/**
 * The floating channel (`/widget/<channel>/eneo.js`) changes only when the
 * bridge protocol itself becomes incompatible with installed snippets.
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
 * Append a new version. An already recorded version can only keep its bytes.
 * manifest.mjs separately requires the previous version's archived assets.
 *
 * @param {Release} built
 * @param {ReleaseRegistry | null} locked
 * @returns {{ release: ReleaseRegistry } | { refused: string }}
 */
export function lockRelease(built, locked) {
  const releases = locked?.releases ?? [];
  const existing = releases.find((release) => release.version === built.version);
  if (existing && !sameBytes(existing, built)) {
    return {
      refused:
        `release.json already records other bytes for ${built.version}. ` +
        `Bump "version" in packages/widget-loader/package.json first.`
    };
  }
  if (existing && existing !== releases.at(-1)) {
    return { refused: `Cannot make archived loader ${built.version} the current version again.` };
  }
  return { release: { releases: existing ? releases : [...releases, built] } };
}
