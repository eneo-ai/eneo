// Copyright (c) 2026 Sundsvalls Kommun

/**
 * Form state for a provider's outbound headers, and the payload it becomes.
 *
 * The header list has replace semantics on the server, keyed by `id`. A secret
 * header's value is never returned (the server sends a mask), so the form keeps
 * it by omitting `value` from the entry; typing a new value replaces it. The
 * same holds for a secret header's fallback. After "Change" the admin can go
 * back to the stored value, as long as the header is still secret.
 */

import type {
  OutboundHeaderInput,
  OutboundHeaderOptions,
  OutboundHeaderPublic
} from "@eneo/eneo-js";

export type HeaderEncoding = NonNullable<OutboundHeaderInput["encoding"]>;
export type HeaderOnMissing = NonNullable<OutboundHeaderInput["on_missing"]>;
export type TokenClassification = OutboundHeaderOptions["dynamic_values"][number]["classification"];

export type HeaderRow = {
  /** Stable key for rendering; not sent. */
  key: string;
  id: string | null;
  name: string;
  value: string;
  /** A stored secret value exists and has not been replaced in this edit. */
  keepsStoredValue: boolean;
  /** A stored secret value exists that the edit can go back to. */
  hasStoredValue: boolean;
  encoding: HeaderEncoding;
  secret: boolean;
  /** Whether the stored header was secret, before this edit. */
  wasSecret: boolean;
  onMissing: HeaderOnMissing;
  fallback: string;
  keepsStoredFallback: boolean;
  hasStoredFallback: boolean;
  /** The server's classification of the stored value, which the form cannot read. */
  storedClassification: TokenClassification | null;
};

export type StoredPart = "value" | "fallback";

const TOKEN = /\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g;

let optionsPromise: Promise<OutboundHeaderOptions> | null = null;

/** Server-owned editor metadata, fetched once per session like capabilities. */
export function loadOutboundHeaderOptions(eneo: {
  modelProviders: { getOutboundHeaderOptions(): Promise<OutboundHeaderOptions> };
}): Promise<OutboundHeaderOptions> {
  optionsPromise ??= eneo.modelProviders.getOutboundHeaderOptions().catch((error: unknown) => {
    optionsPromise = null;
    throw error;
  });
  return optionsPromise;
}

let nextKey = 0;
function rowKey(): string {
  nextKey += 1;
  return `header-${nextKey}`;
}

export function newHeaderRow(): HeaderRow {
  return {
    key: rowKey(),
    id: null,
    name: "",
    value: "",
    keepsStoredValue: false,
    hasStoredValue: false,
    encoding: "percent",
    secret: false,
    wasSecret: false,
    onMissing: "omit",
    fallback: "",
    keepsStoredFallback: false,
    hasStoredFallback: false,
    storedClassification: null
  };
}

export function rowsFromHeaders(headers: OutboundHeaderPublic[] | undefined): HeaderRow[] {
  return (headers ?? []).map((header) => {
    const hasStoredFallback = header.secret && header.fallback != null;
    return {
      key: rowKey(),
      id: header.id,
      name: header.name,
      // A secret's value arrives masked; never seed the mask into an input.
      value: header.secret ? "" : header.value,
      keepsStoredValue: header.secret,
      hasStoredValue: header.secret,
      encoding: header.encoding,
      secret: header.secret,
      wasSecret: header.secret,
      onMissing: header.on_missing,
      fallback: header.secret ? "" : (header.fallback ?? ""),
      keepsStoredFallback: hasStoredFallback,
      hasStoredFallback,
      storedClassification: header.classification ?? null
    };
  });
}

/**
 * Turning `secret` off on a stored secret needs the value typed again: the
 * server refuses to expose a value the admin could not retype. Turning it back
 * on before typing anything returns to the stored value.
 */
export function setSecret(row: HeaderRow, secret: boolean): HeaderRow {
  if (!secret && row.wasSecret) {
    return { ...row, secret, keepsStoredValue: false, keepsStoredFallback: false };
  }
  if (secret && row.wasSecret) {
    return {
      ...row,
      secret,
      keepsStoredValue: row.keepsStoredValue || (row.hasStoredValue && !row.value),
      keepsStoredFallback: row.keepsStoredFallback || (row.hasStoredFallback && !row.fallback)
    };
  }
  return { ...row, secret };
}

/** "Change": replace the stored value (or fallback) with one typed now. */
export function changeStored(row: HeaderRow, part: StoredPart): HeaderRow {
  return part === "value"
    ? { ...row, keepsStoredValue: false, value: "" }
    : { ...row, keepsStoredFallback: false, fallback: "" };
}

/** Whether "Cancel and keep current …" can be offered for `part`. */
export function canKeepStored(row: HeaderRow, part: StoredPart): boolean {
  if (!row.secret) return false;
  return part === "value"
    ? row.hasStoredValue && !row.keepsStoredValue
    : row.hasStoredFallback && !row.keepsStoredFallback;
}

/** Undo "Change": go back to the stored value (or fallback). */
export function keepStored(row: HeaderRow, part: StoredPart): HeaderRow {
  if (!canKeepStored(row, part)) return row;
  return part === "value"
    ? { ...row, keepsStoredValue: true, value: "" }
    : { ...row, keepsStoredFallback: true, fallback: "" };
}

export function headersPayload(rows: HeaderRow[]): OutboundHeaderInput[] {
  return rows.map((row) => {
    const entry: OutboundHeaderInput = {
      name: row.name.trim(),
      encoding: row.encoding,
      secret: row.secret,
      on_missing: row.onMissing
    };
    if (row.id) entry.id = row.id;
    if (!row.keepsStoredValue) entry.value = row.value;
    if (!row.keepsStoredFallback) entry.fallback = row.fallback ? row.fallback : null;
    return entry;
  });
}

export function tokensIn(value: string): string[] {
  return [...value.matchAll(TOKEN)].map((match) => match[1]);
}

export function insertToken(value: string, token: string): string {
  return `${value}{{${token}}}`;
}

/**
 * The notice to show: the highest classification among the tokens in use. A
 * row keeping its stored secret value uses the server's classification of it.
 */
export function headerClassification(
  rows: HeaderRow[],
  options: OutboundHeaderOptions | null
): TokenClassification | null {
  if (!options) return null;
  const byToken = new Map(options.dynamic_values.map((value) => [value.token, value]));
  const classifications = rows.flatMap((row) =>
    row.keepsStoredValue
      ? [row.storedClassification]
      : tokensIn(row.value).map((token) => byToken.get(token)?.classification)
  );
  if (classifications.includes("identifying")) return "identifying";
  if (classifications.includes("organisational")) return "organisational";
  return null;
}

export type TokenProblems = { unknown: string[]; malformed: boolean };

/**
 * What the server would refuse at save: tokens outside the registry, and
 * braces that do not form a token. Mirrors `validate_headers`.
 */
export function tokenProblems(
  value: string,
  options: OutboundHeaderOptions | null
): TokenProblems | null {
  if (!options) return null;
  const known = new Set(options.dynamic_values.map((dynamicValue) => dynamicValue.token));
  const unknown = [...new Set(tokensIn(value).filter((token) => !known.has(token)))];
  const literal = value.replace(TOKEN, "");
  const malformed = literal.includes("{{") || literal.includes("}}");
  return unknown.length > 0 || malformed ? { unknown, malformed } : null;
}

const LOOPBACK_HOSTS = new Set(["localhost", "[::1]"]);

/**
 * A plain http endpoint off this machine: secret values would travel
 * unencrypted. Loopback is exempt, since nothing leaves the host.
 */
export function isUnencryptedRemote(endpoint: string | null | undefined): boolean {
  let url: URL;
  try {
    url = new URL((endpoint ?? "").trim());
  } catch {
    return false;
  }
  if (url.protocol !== "http:") return false;
  const host = url.hostname.toLowerCase();
  return !LOOPBACK_HOSTS.has(host) && !/^127(\.\d{1,3}){3}$/.test(host);
}

export function supportsOutboundHeaders(
  options: OutboundHeaderOptions | null,
  providerType: string
): boolean {
  return options?.supported_provider_types.includes(providerType.toLowerCase()) ?? false;
}

/** Client-side completeness only; the server validates everything else. */
export function isRowComplete(
  row: HeaderRow,
  options: OutboundHeaderOptions | null = null
): boolean {
  if (!row.name.trim()) return false;
  if (!row.keepsStoredValue && !row.value) return false;
  if (!row.keepsStoredValue && tokenProblems(row.value, options)) return false;
  if (row.onMissing === "fallback" && !row.keepsStoredFallback && !row.fallback) return false;
  return true;
}
