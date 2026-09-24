/**
 * The API's allowed-origin rule (`normalize_origin_pattern`), mirrored so a
 * pasted page address is caught in the field instead of failing the save.
 */

export const MAX_ALLOWED_ORIGINS = 20;

const HOST = /^(\*\.)?[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$/i;
const IPV6_HOST = /^[0-9a-f:.]+$/i;
const PORT = /^\d+$/;

/** Whether a bracketed host is an IPv6 address, as the API's URL parser checks it. */
function isIpv6(host: string): boolean {
  if (!IPV6_HOST.test(host)) return false;
  try {
    return new URL(`http://[${host}]/`).hostname !== "";
  } catch {
    return false;
  }
}

/** `scheme://host[:port]` in the API's canonical form, or null when the API would refuse it. */
export function normalizeOrigin(raw: string): string | null {
  const value = raw.trim().replace(/\/+$/, "");
  if (/\s/.test(value)) return null;
  const match = /^(https?):\/\/([^/?#]*)$/i.exec(value);
  if (!match) return null;
  const [, scheme, authority] = match;
  if (authority.includes("@")) return null;

  let host = authority;
  let port: string | null = null;
  if (authority.startsWith("[")) {
    const end = authority.indexOf("]");
    if (end < 0) return null;
    host = authority.slice(1, end);
    const rest = authority.slice(end + 1);
    // The API reads the colons of a bare IPv6 literal as a malformed port.
    if (!rest.startsWith(":")) return null;
    port = rest.slice(1);
    if (!isIpv6(host)) return null;
  } else {
    const colon = authority.lastIndexOf(":");
    if (colon >= 0) {
      host = authority.slice(0, colon);
      port = authority.slice(colon + 1);
    }
    if (!HOST.test(host)) return null;
  }
  if (!host) return null;
  if (port !== null && port !== "*" && !(PORT.test(port) && Number(port) <= 65535)) return null;
  return `${scheme.toLowerCase()}://${authority.toLowerCase()}`;
}

export type ParsedOrigins = {
  /** Canonical, de-duplicated origins from the valid lines. */
  origins: string[];
  /** Lines the API would refuse, as typed. */
  invalid: string[];
  tooMany: boolean;
};

/** One origin per line, as the allowed-websites field takes them. */
export function parseOrigins(text: string): ParsedOrigins {
  const origins: string[] = [];
  const invalid: string[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const origin = normalizeOrigin(trimmed);
    if (origin === null) invalid.push(trimmed);
    else if (!origins.includes(origin)) origins.push(origin);
  }
  return { origins, invalid, tooMany: origins.length > MAX_ALLOWED_ORIGINS };
}
