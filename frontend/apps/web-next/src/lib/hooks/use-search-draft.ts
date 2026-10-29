import { useState } from "react";
import { useDebouncedValue } from "./use-debounced-value";

/** A local search draft; a different committed URL value replaces pending typing. */
export function useSearchDraft(value: string) {
  const [edit, setEdit] = useState({ source: value, draft: value });
  if (edit.source !== value) setEdit({ source: value, draft: value });
  const trimmed = edit.draft.trim();
  const debounced = useDebouncedValue(trimmed);
  return {
    draft: edit.draft,
    setDraft: (draft: string) => setEdit((current) => ({ ...current, draft })),
    // An old timer must not commit over a newly restored URL or a cleared draft.
    settled: debounced === trimmed ? debounced : value
  };
}
