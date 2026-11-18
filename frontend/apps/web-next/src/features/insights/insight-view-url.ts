import {
  goHistory,
  pushUrl,
  readUrlState,
  replaceUrl,
  usePathname,
  useSearchParams
} from "@/lib/navigation";
import {
  parseFeedbackFilter,
  parseOpenableFinding,
  type FeedbackFilter,
  type OpenableFindingKind
} from "./insight-figures";

type SearchReader = Pick<URLSearchParams, "get">;

/**
 * The address's parameters that only choose a view of the insights: the
 * finding open in place of the overview (`finding`), the feedback inbox's
 * filter (`feedback`) and the analysis open over the view (`analysis`). A
 * page showing the insights counts them among its view parameters
 * (`ViewSearchParams`), keeps them while the insights are on screen and
 * drops them when it leaves them.
 */
export const INSIGHT_VIEW_PARAMS = ["finding", "feedback", "analysis"] as const;

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

/** The feedback inbox's filter (`feedback`); left out or unknown is every rating. */
export function readInsightFeedbackSearch(params: SearchReader): FeedbackFilter {
  return parseFeedbackFilter(params.get("feedback"));
}

/** The address's query with the inbox's filter in it (every rating: left out); other parameters stay. */
export function insightFeedbackSearch(feedback: FeedbackFilter, current = ""): string {
  const params = new URLSearchParams(current);
  if (feedback === "all") params.delete("feedback");
  else params.set("feedback", feedback);
  return `?${params.toString()}`;
}

/** The analysis open over the view (`analysis=open`). */
export function readInsightAnalysisSearch(params: SearchReader): boolean {
  return params.get("analysis") === "open";
}

/** The address's query with the analysis open over the view or not; other parameters stay. */
export function insightAnalysisSearch(open: boolean, current = ""): string {
  const params = new URLSearchParams(current);
  if (open) params.set("analysis", "open");
  else params.delete("analysis");
  return `?${params.toString()}`;
}

/** Where the insights view is, as the address keeps it, and the ways to move. */
export type InsightView = {
  finding: OpenableFindingKind | null;
  feedback: FeedbackFilter;
  /** The entry on screen is the one "Läs kommentarerna" pushed from the overview behind it. */
  isReadingComments: boolean;
  /** Opens a finding in place of the overview, or (none) goes back to the overview. */
  onFindingChange: (finding: OpenableFindingKind | null) => void;
  /** The inbox's own filter control: the address changes in place. */
  onFeedbackChange: (feedback: FeedbackFilter) => void;
  /** "Läs kommentarerna": the inbox filtered to the bad ratings with a comment. */
  readComments: () => void;
  /** The analysis is open over the view, as a place of its own. */
  analysis: boolean;
  /** Opens the analysis over the view. */
  openAnalysis: () => void;
  /** Closes the analysis opened over the view, showing what is under it. */
  closeAnalysis: () => void;
};

/**
 * The insights view's place in the address, each move a history entry where
 * the browser's Back should undo it. Neither move is a departure: the page
 * stays mounted, so no leave guard asks.
 *
 * Opening a finding pushes an entry, so Back returns to the overview and
 * Forward opens the finding again; a reload or a shared link opens it too.
 * The entry remembers the overview's address it was opened from. The way
 * back returns to that entry while the address is still that overview's with
 * the finding in it, so the overview is not added twice; otherwise (a link,
 * a filter changed on the finding) it shows the overview in place.
 *
 * "Läs kommentarerna" pushes an entry with the inbox filtered to the bad
 * ratings with a comment, marked as its own, so Back returns to the overview
 * with the filter it had. Asked again from that entry it sets the filter in
 * place, and where the inbox already shows them there is nothing to undo.
 * The inbox's own filter control changes the address in place.
 *
 * The analysis opened over the view (a narrow window, a phone: it covers
 * the view like a pushed screen) is an entry of its own, so Back closes it
 * and Forward opens it again; a reload or a link opens it too. Closing it
 * returns to the entry its opening pushed while the address is still that
 * one's with the analysis in it, and closes it in place otherwise. The
 * analysis beside the view is the view's own layout, not an entry.
 */
export function useInsightViewUrl(): InsightView {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  const feedback = readInsightFeedbackSearch(searchParams);
  const isReadingComments = readUrlState().insightCommentsFromFinding === true;
  const overview = pathname + insightFindingSearch(null, search);
  const analysis = readInsightAnalysisSearch(searchParams);
  const underAnalysis = pathname + insightAnalysisSearch(false, search);

  function onFindingChange(next: OpenableFindingKind | null) {
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

  function onFeedbackChange(next: FeedbackFilter) {
    replaceUrl(pathname + insightFeedbackSearch(next, search), { ignoreBlocker: true });
  }

  function readComments() {
    if (feedback === "bad_commented") return;
    const comments = pathname + insightFeedbackSearch("bad_commented", search);
    if (isReadingComments) replaceUrl(comments, { ignoreBlocker: true });
    else {
      pushUrl(comments, { state: { insightCommentsFromFinding: true }, ignoreBlocker: true });
    }
  }

  function openAnalysis() {
    if (analysis) return;
    // The view under it stays what it was, "Läs kommentarerna"'s included.
    pushUrl(pathname + insightAnalysisSearch(true, search), {
      state: {
        insightAnalysisFrom: underAnalysis,
        insightCommentsFromFinding: readUrlState().insightCommentsFromFinding
      },
      ignoreBlocker: true
    });
  }

  function closeAnalysis() {
    if (!analysis) return;
    if (readUrlState().insightAnalysisFrom === underAnalysis) {
      goHistory(-1, { ignoreBlocker: true });
    } else {
      replaceUrl(underAnalysis, { state: { insightAnalysisFrom: undefined }, ignoreBlocker: true });
    }
  }

  return {
    finding: readInsightFindingSearch(searchParams),
    feedback,
    isReadingComments,
    onFindingChange,
    onFeedbackChange,
    readComments,
    analysis,
    openAnalysis,
    closeAnalysis
  };
}
