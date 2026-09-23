/**
 * A word-level difference between two texts, so an instruction's change reads
 * the way a review tool shows it: removed words struck through, added words
 * marked, everything else as it was.
 */
export type DiffPart = {
  kind: "same" | "added" | "removed";
  text: string;
  /** Whitespace at the edge of a change: it belongs to its side, unmarked. */
  plain?: boolean;
};

// A template reference stays one token (it renders as a step badge), then
// words, runs of whitespace and single marks: changing one word marks that
// word, not its line.
const TOKEN = /\{\{[^{}]*\}\}|\s+|[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu;

// ponytail: quadratic longest common subsequence over the changed middle; past
// this many cells the caller shows the plain before and after instead.
const MAX_CELLS = 4_000_000;

export function wordDiff(before: string, after: string): DiffPart[] | null {
  const a = before.match(TOKEN) ?? [];
  const b = after.match(TOKEN) ?? [];
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA -= 1;
    endB -= 1;
  }
  const midA = a.slice(start, endA);
  const midB = b.slice(start, endB);
  if ((midA.length + 1) * (midB.length + 1) > MAX_CELLS) return null;

  const lcs = Array.from({ length: midA.length + 1 }, () => new Uint32Array(midB.length + 1));
  for (let i = midA.length - 1; i >= 0; i -= 1) {
    for (let j = midB.length - 1; j >= 0; j -= 1) {
      lcs[i][j] =
        midA[i] === midB[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const raw: DiffPart[] = a.slice(0, start).map((text) => ({ kind: "same", text }));
  let i = 0;
  let j = 0;
  while (i < midA.length && j < midB.length) {
    if (midA[i] === midB[j]) {
      raw.push({ kind: "same", text: midA[i] });
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      raw.push({ kind: "removed", text: midA[i] });
      i += 1;
    } else {
      raw.push({ kind: "added", text: midB[j] });
      j += 1;
    }
  }
  for (; i < midA.length; i += 1) raw.push({ kind: "removed", text: midA[i] });
  for (; j < midB.length; j += 1) raw.push({ kind: "added", text: midB[j] });
  for (const text of a.slice(endA)) raw.push({ kind: "same", text });
  return regroup(raw);
}

/**
 * One change reads as one struck phrase and one marked phrase: a lone space
 * that happens to match between two changed words joins the change instead
 * of splitting it into word-by-word alternation.
 */
function regroup(raw: DiffPart[]): DiffPart[] {
  const blank = (part: DiffPart) => /^\s+$/.test(part.text);
  // For each part, the kind of the next part that is not whitespace.
  const nextKind: (DiffPart["kind"] | null)[] = new Array(raw.length).fill(null);
  let upcoming: DiffPart["kind"] | null = null;
  for (let index = raw.length - 1; index >= 0; index -= 1) {
    nextKind[index] = upcoming;
    if (!blank(raw[index])) upcoming = raw[index].kind;
  }

  const parts: DiffPart[] = [];
  let removed = "";
  let added = "";
  // A change is marked from its first to its last visible character, line by
  // line: the spaces and line breaks around and inside it stay on their side,
  // unmarked, so no empty line carries a mark.
  const pushChange = (kind: "removed" | "added", text: string) => {
    for (const piece of text.split(/(\s*\n\s*)/)) {
      if (!piece) continue;
      const [, lead, core, trail] = /^(\s*)([\s\S]*?)(\s*)$/.exec(piece) ?? ["", "", piece, ""];
      if (lead) parts.push({ kind, text: lead, plain: true });
      if (core) parts.push({ kind, text: core });
      if (trail) parts.push({ kind, text: trail, plain: true });
    }
  };
  const flush = () => {
    if (removed) pushChange("removed", removed);
    if (added) pushChange("added", added);
    removed = "";
    added = "";
  };
  raw.forEach((part, index) => {
    const next = nextKind[index];
    if (part.kind === "removed") removed += part.text;
    else if (part.kind === "added") added += part.text;
    else if ((removed || added) && blank(part) && next !== null && next !== "same") {
      removed += part.text;
      added += part.text;
    } else {
      flush();
      const last = parts.at(-1);
      if (last?.kind === "same") last.text += part.text;
      else parts.push({ kind: "same", text: part.text });
    }
  });
  flush();
  return parts;
}

/** One item of the marked view; a marker stands for spacing that changed. */
export type MarkedPart = DiffPart & { marker?: "break" | "space" };

/**
 * The marked view reads as the new text: added words marked, removed words
 * struck where they stood, spacing as it is now. A change of spacing alone has
 * no word to mark, so it shows as one marker (a line break or a space that
 * came or went); the split view keeps both texts exactly.
 */
export function markedView(parts: DiffPart[]): MarkedPart[] {
  const view: MarkedPart[] = [];
  let change: DiffPart[] = [];
  const endChange = () => {
    if (change.length > 0 && change.every((part) => part.plain)) {
      // Which side had more of it: line breaks first, then any spacing.
      const count = (kind: DiffPart["kind"], pattern: RegExp) =>
        change
          .filter((part) => part.kind === kind)
          .reduce((sum, part) => sum + (part.text.match(pattern)?.length ?? 0), 0);
      const breaks = count("removed", /\n/g) - count("added", /\n/g);
      const isBreak = breaks !== 0;
      const kind = isBreak
        ? breaks > 0
          ? "removed"
          : "added"
        : count("removed", /\s/g) > count("added", /\s/g)
          ? "removed"
          : "added";
      view.push({ kind, text: isBreak ? "¶" : "·", marker: isBreak ? "break" : "space" });
    }
    for (const part of change) {
      if (!part.plain) view.push(part);
      else if (part.kind === "added") view.push({ kind: "same", text: part.text });
    }
    change = [];
  };
  for (const part of parts) {
    if (part.kind === "same") {
      endChange();
      view.push(part);
    } else {
      change.push(part);
    }
  }
  endChange();
  return view;
}
