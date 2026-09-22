import data from "../releases.json";
import schema from "../releases.schema.json";

/** @type {import("./index").Release[]} */
export const releases = data.releases;

// The JSON schema is the single source for the closed vocabularies. The
// TypeScript unions in index.d.ts mirror them; the web app's tests assert
// that its label maps cover these runtime lists so a new value cannot ship
// without a label.
/** @type {readonly import("./index").EntryType[]} */
export const ENTRY_TYPES = schema.$defs.entry.properties.type.enum;
/** @type {readonly import("./index").EntryArea[]} */
export const ENTRY_AREAS = schema.$defs.entry.properties.area.enum;
/** @type {readonly import("./index").EntryAudience[]} */
export const ENTRY_AUDIENCES = schema.$defs.entry.properties.audience.enum;
/** @type {readonly import("./index").Locale[]} */
export const LOCALES = schema.$defs.localized.required;

export function latestRelease() {
  return releases[0];
}

/**
 * Semver order for release ids as written in releases.json ("2.2.0",
 * "2.3.0-rc.1"). A pre-release sorts before its final release; pre-release
 * identifiers compare numerically when both are numeric, otherwise as text.
 * @param {string} a
 * @param {string} b
 * @returns {number} negative when a < b, 0 when equal, positive when a > b
 */
export function compareVersions(a, b) {
  const pa = parseVersion(a);
  const pb = parseVersion(b);
  for (let i = 0; i < 3; i++) {
    if (pa.core[i] !== pb.core[i]) return pa.core[i] - pb.core[i];
  }
  if (pa.pre.length === 0 && pb.pre.length === 0) return 0;
  if (pa.pre.length === 0) return 1;
  if (pb.pre.length === 0) return -1;
  const len = Math.max(pa.pre.length, pb.pre.length);
  for (let i = 0; i < len; i++) {
    const x = pa.pre[i];
    const y = pb.pre[i];
    if (x === undefined) return -1;
    if (y === undefined) return 1;
    const nx = /^\d+$/.test(x) ? Number(x) : null;
    const ny = /^\d+$/.test(y) ? Number(y) : null;
    if (nx !== null && ny !== null) {
      if (nx !== ny) return nx - ny;
    } else if (nx !== null) {
      return -1;
    } else if (ny !== null) {
      return 1;
    } else if (x !== y) {
      return x < y ? -1 : 1;
    }
  }
  return 0;
}

/** @param {string} version */
function parseVersion(version) {
  const separator = version.indexOf("-");
  const core = separator === -1 ? version : version.slice(0, separator);
  const pre = separator === -1 ? "" : version.slice(separator + 1);
  return {
    core: core.split(".").map(Number),
    pre: pre ? pre.split(".") : []
  };
}

/**
 * True while the newest bundled release is newer than what the user has
 * seen. Comparing by order (not equality) keeps the dot off after a
 * rollback or when an older frontend serves a request mid-deploy.
 * @param {string | null | undefined} seenVersion
 */
export function hasUnseenRelease(seenVersion) {
  const latest = latestRelease();
  if (!latest) return false;
  if (!seenVersion) return true;
  return compareVersions(latest.version, seenVersion) > 0;
}

/**
 * @param {import("./index").Release} release
 * @param {boolean} isAdmin
 */
export function visibleEntries(release, isAdmin) {
  return release.entries.filter((entry) => isAdmin || (entry.audience ?? "all") === "all");
}
