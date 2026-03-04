export type HighlightGroupInput = {
  group: string;
  snippets: string[];
};

export interface FlowDocumentHighlighter {
  highlight(groups: HighlightGroupInput[]): number;
  setActive(snippet: string): void;
  clearGroup(group: string): void;
  clearAll(): void;
  getMatchCount(group?: string): number;
  scrollToFirstMatch(group: string): void;
  scrollToNextMatch(): void;
  scrollToPrevMatch(): void;
  destroy(): void;
}

type TextMatch = {
  node: Text;
  nodeIndex: number;
  start: number;
  end: number;
};

export function createDocumentHighlighter(container: HTMLElement): FlowDocumentHighlighter {
  if (supportsNativeHighlights()) {
    return new NativeHighlighter(container);
  }
  return new FallbackHighlighter(container);
}

function supportsNativeHighlights(): boolean {
  const runtime = globalThis as {
    CSS?: { highlights?: { set: (name: string, value: unknown) => void; delete: (name: string) => void } };
    Highlight?: new (...ranges: Range[]) => unknown;
  };
  return Boolean(runtime.CSS?.highlights && runtime.Highlight);
}

function normalizeSnippets(snippets: string[]): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];

  for (const snippet of snippets) {
    const value = snippet.trim();
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    normalized.push(value);
  }

  return normalized;
}

function collectTextMatches(container: HTMLElement, snippets: string[]): TextMatch[] {
  const normalizedSnippets = normalizeSnippets(snippets);
  if (normalizedSnippets.length === 0) {
    return [];
  }

  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const matches: TextMatch[] = [];
  const seen = new Set<string>();
  let nodeIndex = 0;
  let textNode = walker.nextNode() as Text | null;

  while (textNode) {
    const text = textNode.textContent ?? "";
    for (const snippet of normalizedSnippets) {
      let start = text.indexOf(snippet);
      while (start !== -1) {
        const end = start + snippet.length;
        const key = `${nodeIndex}:${start}:${end}`;
        if (!seen.has(key)) {
          seen.add(key);
          matches.push({ node: textNode, nodeIndex, start, end });
        }
        start = text.indexOf(snippet, start + 1);
      }
    }

    nodeIndex += 1;
    textNode = walker.nextNode() as Text | null;
  }

  return matches;
}

class NativeHighlighter implements FlowDocumentHighlighter {
  private readonly container: HTMLElement;
  private readonly rangeMap = new Map<string, Range[]>();
  private currentGroup = "chunk-match";
  private currentMatchIndex = -1;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  highlight(groups: HighlightGroupInput[]): number {
    const highlights = (globalThis as any).CSS?.highlights;
    const HighlightCtor = (globalThis as any).Highlight as (new (...ranges: Range[]) => unknown) | undefined;
    if (!highlights || !HighlightCtor) {
      return 0;
    }

    let totalMatches = 0;
    for (const group of groups) {
      this.clearGroup(group.group);
      const matches = collectTextMatches(this.container, group.snippets);
      if (matches.length === 0) {
        continue;
      }

      const ranges: Range[] = [];
      for (const match of matches) {
        const range = new Range();
        range.setStart(match.node, match.start);
        range.setEnd(match.node, match.end);
        ranges.push(range);
      }
      highlights.set(group.group, new HighlightCtor(...ranges));
      this.rangeMap.set(group.group, ranges);
      totalMatches += ranges.length;
    }

    if (this.rangeMap.has("chunk-match")) {
      this.currentGroup = "chunk-match";
      this.currentMatchIndex = this.rangeMap.get("chunk-match")!.length > 0 ? 0 : -1;
    }
    return totalMatches;
  }

  setActive(snippet: string): void {
    this.highlight([{ group: "chunk-active", snippets: [snippet] }]);
    this.currentGroup = "chunk-active";
    this.scrollToFirstMatch("chunk-active");
  }

  clearGroup(group: string): void {
    (globalThis as any).CSS?.highlights?.delete(group);
    this.rangeMap.delete(group);
    if (this.currentGroup === group) {
      this.currentGroup = "chunk-match";
      this.currentMatchIndex = 0;
    }
  }

  clearAll(): void {
    for (const group of this.rangeMap.keys()) {
      (globalThis as any).CSS?.highlights?.delete(group);
    }
    this.rangeMap.clear();
    this.currentGroup = "chunk-match";
    this.currentMatchIndex = -1;
  }

  getMatchCount(group = "chunk-match"): number {
    return this.rangeMap.get(group)?.length ?? 0;
  }

  scrollToFirstMatch(group: string): void {
    const ranges = this.rangeMap.get(group);
    if (!ranges || ranges.length === 0) {
      return;
    }
    this.currentGroup = group;
    this.currentMatchIndex = 0;
    this.scrollToRange(ranges[0]);
  }

  scrollToNextMatch(): void {
    const ranges = this.rangeMap.get(this.currentGroup);
    if (!ranges || ranges.length === 0) {
      return;
    }
    this.currentMatchIndex = (this.currentMatchIndex + 1) % ranges.length;
    this.scrollToRange(ranges[this.currentMatchIndex]);
  }

  scrollToPrevMatch(): void {
    const ranges = this.rangeMap.get(this.currentGroup);
    if (!ranges || ranges.length === 0) {
      return;
    }
    this.currentMatchIndex = (this.currentMatchIndex - 1 + ranges.length) % ranges.length;
    this.scrollToRange(ranges[this.currentMatchIndex]);
  }

  destroy(): void {
    this.clearAll();
  }

  private scrollToRange(range: Range): void {
    const rect = range.getBoundingClientRect();
    const containerRect = this.container.getBoundingClientRect();
    this.container.scrollTo({
      top: rect.top - containerRect.top + this.container.scrollTop - 80,
      behavior: "smooth",
    });
  }
}

class FallbackHighlighter implements FlowDocumentHighlighter {
  private readonly container: HTMLElement;
  private currentGroup = "chunk-match";
  private currentMatchIndex = -1;

  constructor(container: HTMLElement) {
    this.container = container;
  }

  highlight(groups: HighlightGroupInput[]): number {
    let totalMatches = 0;
    for (const group of groups) {
      this.clearGroup(group.group);
      const matches = collectTextMatches(this.container, group.snippets);
      if (matches.length === 0) {
        continue;
      }

      for (let index = matches.length - 1; index >= 0; index -= 1) {
        const match = matches[index];
        const range = document.createRange();
        range.setStart(match.node, match.start);
        range.setEnd(match.node, match.end);
        const mark = document.createElement("mark");
        mark.dataset.highlightGroup = group.group;
        mark.className = `flow-highlight flow-highlight--${group.group}`;
        range.surroundContents(mark);
      }

      totalMatches += matches.length;
    }

    if (this.getMatchCount("chunk-match") > 0) {
      this.currentGroup = "chunk-match";
      this.currentMatchIndex = 0;
    }

    return totalMatches;
  }

  setActive(snippet: string): void {
    this.highlight([{ group: "chunk-active", snippets: [snippet] }]);
    this.currentGroup = "chunk-active";
    this.scrollToFirstMatch("chunk-active");
  }

  clearGroup(group: string): void {
    const marks = this.container.querySelectorAll(`mark[data-highlight-group="${group}"]`);
    for (const mark of marks) {
      const parent = mark.parentNode;
      if (!parent) {
        continue;
      }
      parent.replaceChild(document.createTextNode(mark.textContent ?? ""), mark);
      parent.normalize();
    }
  }

  clearAll(): void {
    const marks = this.container.querySelectorAll("mark[data-highlight-group]");
    for (const mark of marks) {
      const parent = mark.parentNode;
      if (!parent) {
        continue;
      }
      parent.replaceChild(document.createTextNode(mark.textContent ?? ""), mark);
      parent.normalize();
    }
    this.currentGroup = "chunk-match";
    this.currentMatchIndex = -1;
  }

  getMatchCount(group = "chunk-match"): number {
    return this.container.querySelectorAll(`mark[data-highlight-group="${group}"]`).length;
  }

  scrollToFirstMatch(group: string): void {
    const first = this.container.querySelector(`mark[data-highlight-group="${group}"]`);
    if (!first) {
      return;
    }
    this.currentGroup = group;
    this.currentMatchIndex = 0;
    first.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  scrollToNextMatch(): void {
    const marks = Array.from(
      this.container.querySelectorAll(`mark[data-highlight-group="${this.currentGroup}"]`),
    );
    if (marks.length === 0) {
      return;
    }
    this.currentMatchIndex = (this.currentMatchIndex + 1) % marks.length;
    marks[this.currentMatchIndex].scrollIntoView({ behavior: "smooth", block: "center" });
  }

  scrollToPrevMatch(): void {
    const marks = Array.from(
      this.container.querySelectorAll(`mark[data-highlight-group="${this.currentGroup}"]`),
    );
    if (marks.length === 0) {
      return;
    }
    this.currentMatchIndex = (this.currentMatchIndex - 1 + marks.length) % marks.length;
    marks[this.currentMatchIndex].scrollIntoView({ behavior: "smooth", block: "center" });
  }

  destroy(): void {
    this.clearAll();
  }
}
