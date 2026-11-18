import {
  goHistory,
  pushUrl,
  readUrlState,
  replaceUrl,
  usePathname,
  useSearchParams
} from "@/lib/navigation";
import { parseOpenableFinding, type OpenableFindingKind } from "./insight-figures";

type SearchReader = Pick<URLSearchParams, "get">;

/** The finding open in place of the overview (`finding`); anything unknown is none. */
export function readInsightFindingSearch(params: SearchReader): OpenableFindingKind | null {
  return parseOpenableFinding(params.get("finding"));
}

/** The address's query with the finding in it (none: left out); other parameters stay. */
export function insightFindingSearch(finding: OpenableFindingKind | null, current = ""): string {
  const params = new URLSearchParams(current);
  if (finding) params.set("finding", finding);
  else params.delete("finding");
  return `?${params.toString()}`;
}

/**
 * The finding open in place of the overview, kept in the address (`finding`)
 * as a history entry of its own, and the way to open or close one.
 *
 * Opening one pushes an entry, so the browser's Back returns to the overview
 * and Forward opens the finding again; a reload or a shared link opens it
 * too. The entry remembers the overview's address it was opened from. The
 * way back returns to that entry while the address is still that overview's
 * with the finding in it, so the overview is not added twice; otherwise (a
 * link, a filter changed on the finding) it shows the overview in place.
 * Neither is a departure: the page stays mounted, so no leave guard asks.
 */
export function useInsightFindingUrl(): [
  finding: OpenableFindingKind | null,
  onFindingChange: (finding: OpenableFindingKind | null) => void
] {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  const overview = pathname + insightFindingSearch(null, search);

  function change(next: OpenableFindingKind | null) {
    if (next) {
      pushUrl(pathname + insightFindingSearch(next, search), {
        state: { insightFindingFrom: overview },
        ignoreBlocker: true
      });
    } else if (readUrlState().insightFindingFrom === overview) {
      goHistory(-1, { ignoreBlocker: true });
    } else {
      replaceUrl(overview, { state: { insightFindingFrom: undefined }, ignoreBlocker: true });
    }
  }

  return [readInsightFindingSearch(searchParams), change];
}
