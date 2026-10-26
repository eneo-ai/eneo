export interface WebsiteContentFilters {
  /** A URL directory, with its trailing slash; empty selects the whole website. */
  prefix: string;
  /** Title and URL search below the selected directory. */
  q: string;
}

/** The content filters a page URL carries. Values the API would reject fall back to no filter. */
export function readContentFilters(params: URLSearchParams): WebsiteContentFilters {
  const prefix = params.get("prefix") ?? "";
  return {
    prefix: /^https?:\/\/[^?#]+\/$/.test(prefix) && prefix.length <= 2048 ? prefix : "",
    q: (params.get("q") ?? "").trim().slice(0, 200)
  };
}
