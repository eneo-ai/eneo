export type WebsiteContentSearch = { tab: "crawls" | "blobs"; prefix: string; q: string };

/** Match the website API's URL-directory and search bounds before making a request. */
export function readWebsiteContentSearch(
  params: Pick<URLSearchParams, "get">
): WebsiteContentSearch {
  const prefix = params.get("prefix") ?? "";
  return {
    tab: params.get("tab") === "blobs" ? "blobs" : "crawls",
    prefix: /^https?:\/\/[^?#]+\/$/.test(prefix) && prefix.length <= 2048 ? prefix : "",
    q: (params.get("q") ?? "").trim().slice(0, 200)
  };
}

export function websiteContentHref(
  pathname: string,
  current: Pick<URLSearchParams, "toString">,
  view: WebsiteContentSearch
) {
  const params = new URLSearchParams(current.toString());
  for (const [key, value] of Object.entries(view)) {
    if (value) params.set(key, value);
    else params.delete(key);
  }
  return `${pathname}?${params}`;
}
