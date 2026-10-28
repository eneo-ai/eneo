/**
 * The router's search serialization: flat `URLSearchParams`, as the address
 * bar, Next and the backend read a query. TanStack's default JSON-parses
 * values (`?page=2` would become the number 2, `?tab=a&tab=b` would keep only
 * one); here every value stays a string, a repeated key becomes a list, and
 * an address written by hand or by Next comes back unchanged.
 */
export type FlatSearch = Record<string, string | string[]>;

/** `?a=1&b=x&b=y` → `{ a: "1", b: ["x", "y"] }`; values are never parsed further. */
export function parseSearch(searchStr: string): FlatSearch {
  const search: FlatSearch = {};
  for (const [key, value] of new URLSearchParams(searchStr)) {
    const current = search[key];
    if (current === undefined) search[key] = value;
    else if (Array.isArray(current)) current.push(value);
    else search[key] = [current, value];
  }
  return search;
}

/**
 * The query for `search`, `""` or `?…`: a list adds the key once per item,
 * other values go through `String()`, and `undefined` or `null` leave the key
 * out.
 */
export function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item !== undefined && item !== null) params.append(key, String(item));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}
