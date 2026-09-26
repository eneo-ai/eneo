"use client";

import { useTranslations } from "next-intl";
import {
  createContext,
  useContext,
  useMemo,
  useRef,
  type ComponentProps,
  type ReactNode
} from "react";

import { Tooltip } from "@astryxdesign/core/Tooltip";
import { hostOf } from "@/lib/chat/metadata";

/**
 * Inline citations. A remark plugin rewrites `[N]` markers in the answer text
 * (N a 1-based index into the message's merged sources) into `#<prefix>-cite-N`
 * link nodes, and the `a` component override renders exactly those (the
 * message's own prefix, N within its sources) as small numbered chips named
 * "Källa N: <titel>". Any other link stays a plain link, so a link in the
 * model's output can never pose as a source. Operating on the markdown AST
 * (not a string regex) means code blocks and existing links are left untouched.
 *
 * Real backend answers cite via `<inref id="…"/>` tags; lib/chat/inref.ts
 * rewrites those to `[N]` before the text reaches this plugin.
 *
 * The chip is a real button (keyboard reachable, WCAG 2.1.1): it opens the
 * source in the activity panel instead of navigating. It has the look of the
 * Astryx `Citation` number badge but is not that component, which renders a
 * link that forces `target="_blank"` and a native `title`.
 */

type MdNode = {
  type: string;
  value?: string;
  url?: string;
  children?: MdNode[];
};

function splitCitations(value: string, sourceCount: number, prefix: string): MdNode[] {
  const out: MdNode[] = [];
  const regex = /\[(\d{1,3})\]/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(value)) !== null) {
    const n = Number(match[1]);
    if (n < 1 || n > sourceCount) continue;
    if (match.index > last) out.push({ type: "text", value: value.slice(last, match.index) });
    out.push({
      type: "link",
      url: `#${prefix}-cite-${n}`,
      children: [{ type: "text", value: String(n) }]
    });
    last = match.index + match[0].length;
  }
  if (out.length === 0) return [{ type: "text", value }];
  if (last < value.length) out.push({ type: "text", value: value.slice(last) });
  return out;
}

function transform(node: MdNode, sourceCount: number, prefix: string) {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === "text" && child.value && /\[\d{1,3}\]/.test(child.value)) {
      next.push(...splitCitations(child.value, sourceCount, prefix));
    } else {
      // Don't descend into code/inline-code: a citation there would be noise.
      if (child.type !== "code" && child.type !== "inlineCode") {
        transform(child, sourceCount, prefix);
      }
      next.push(child);
    }
  }
  node.children = next;
}

/** remark plugin factory: rewrites `[N]` (1 ≤ N ≤ sourceCount) into `#{prefix}-cite-N` links. */
export function remarkCitations(sourceCount: number, prefix: string) {
  return () => (tree: MdNode) => {
    if (sourceCount > 0) transform(tree, sourceCount, prefix);
  };
}

/**
 * The citation remark plugin list for a message, stable while the source count
 * and prefix stay the same (MessageResponse re-parses every block when its
 * plugin list changes identity).
 */
export function useCitationRemarkPlugins(sourceCount: number, prefix: string) {
  return useMemo(() => [remarkCitations(sourceCount, prefix)], [sourceCount, prefix]);
}

/** The minimal source shape a citation needs to name and preview itself. */
export type CitationSource = { title: string; url?: string };

type CitationContextValue = {
  sources: CitationSource[];
  /** The message's citation link prefix (the `prefix` given to remarkCitations). */
  prefix: string;
  /**
   * Opens source `index` (0-based), e.g. in the activity panel's source list.
   * `trigger` is the citation chip, for returning focus when that view closes.
   */
  onOpenSource: (index: number, trigger: HTMLElement) => void;
};

const CitationSourcesContext = createContext<CitationContextValue | null>(null);

/** Provides the message's ordered sources so inline citations can name and open them. */
export function CitationSourcesProvider({
  value,
  prefix,
  onOpenSource,
  children
}: {
  value: CitationSource[];
  prefix: string;
  onOpenSource: (index: number, trigger: HTMLElement) => void;
  children: ReactNode;
}) {
  const context = useMemo(
    () => ({ sources: value, prefix, onOpenSource }),
    [value, prefix, onOpenSource]
  );
  return (
    <CitationSourcesContext.Provider value={context}>{children}</CitationSourcesContext.Provider>
  );
}

/**
 * The 1-based source number a citation link generated for this message points
 * at: exactly `#<prefix>-cite-N`, N within the sources. Null for anything else.
 */
export function citationNumber(
  href: string | undefined,
  prefix: string,
  sourceCount: number
): number | null {
  const marker = `#${prefix}-cite-`;
  if (!href?.startsWith(marker)) return null;
  const digits = href.slice(marker.length);
  if (!/^\d{1,3}$/.test(digits)) return null;
  const number = Number(digits);
  return number >= 1 && number <= sourceCount ? number : null;
}

const CHIP_CLASS =
  "bg-ax-accent-muted text-ax-text-accent hover:bg-ax-hover focus-visible:outline-ring mx-0.5 inline-flex h-[1.125rem] min-w-[1.125rem] cursor-pointer items-center justify-center rounded-ax-inner px-1 align-[0.15em] font-sans text-[11px] leading-none font-bold focus-visible:outline-2 focus-visible:outline-offset-2";

function CitationChip({
  number,
  source,
  onOpen,
  children
}: {
  number: number;
  source: CitationSource;
  onOpen: (index: number, trigger: HTMLElement) => void;
  children: ReactNode;
}) {
  const t = useTranslations();
  const ref = useRef<HTMLButtonElement>(null);
  const host = hostOf(source.url);
  return (
    <>
      <button
        ref={ref}
        type="button"
        aria-label={t("chat_citation_label", { number, title: source.title })}
        onClick={(event) => onOpen(number - 1, event.currentTarget)}
        className={CHIP_CLASS}
      >
        {children}
      </button>
      {/* Sibling mode: the tooltip portals out, so nothing block-level lands
          inside the answer's <p>. */}
      <Tooltip
        anchorRef={ref}
        content={
          <span className="flex max-w-xs flex-col">
            <span className="font-medium">{source.title}</span>
            {host && <span>{host}</span>}
          </span>
        }
      />
    </>
  );
}

function CitationLink({
  href,
  children,
  node: _node,
  ...props
}: ComponentProps<"a"> & { node?: unknown }) {
  const citations = useContext(CitationSourcesContext);
  const number = citations
    ? citationNumber(href, citations.prefix, citations.sources.length)
    : null;

  if (citations && number !== null) {
    return (
      <CitationChip
        number={number}
        source={citations.sources[number - 1]!}
        onOpen={citations.onOpenSource}
      >
        {children}
      </CitationChip>
    );
  }

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-ax-text-accent underline underline-offset-2"
      {...props}
    >
      {children}
    </a>
  );
}

/** Pass to <MessageResponse components={citationComponents}> so `#…-cite-N` links render as chips. */
export const citationComponents = { a: CitationLink };
