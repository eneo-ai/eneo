"use client";

import { createContext, useContext, type ComponentProps, type ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/**
 * Inline citations. A remark plugin rewrites `[N]` markers in the answer text
 * (N a 1-based index into the message's merged sources) into anchor links, and
 * the `a` component override renders those as small superscript chips that jump
 * to the matching source chip. Operating on the markdown AST (not a string
 * regex) means code blocks and existing links are left untouched.
 *
 * Real backend answers cite via `<inref id="…"/>` tags; lib/chat/inref.ts
 * rewrites those to `[N]` before the text reaches this plugin.
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

/** The minimal source shape a citation needs to preview on hover. */
export type CitationSource = { title: string; url?: string };

const CitationSourcesContext = createContext<CitationSource[]>([]);

/** Provides the message's ordered sources so inline citations can preview them on hover. */
export function CitationSourcesProvider({
  value,
  children
}: {
  value: CitationSource[];
  children: ReactNode;
}) {
  return (
    <CitationSourcesContext.Provider value={value}>{children}</CitationSourcesContext.Provider>
  );
}

function hostOf(url?: string): string | undefined {
  if (!url) return undefined;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return undefined;
  }
}

function CitationLink({ href, children, ...props }: ComponentProps<"a">) {
  const sources = useContext(CitationSourcesContext);
  const match = href?.match(/-cite-(\d+)$/);

  if (match) {
    const source = sources[Number(match[1]) - 1];
    const chip = (
      <a href={href} className="text-primary no-underline">
        <sup className="bg-primary/10 text-primary ml-0.5 rounded-[3px] px-1 py-px text-[0.7em] font-medium">
          {children}
        </sup>
      </a>
    );
    if (!source) return chip;
    const host = hostOf(source.url);
    return (
      <Tooltip>
        <TooltipTrigger asChild>{chip}</TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <p className="font-medium">{source.title}</p>
          {host && <p className="text-background/70">{host}</p>}
        </TooltipContent>
      </Tooltip>
    );
  }

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-primary underline underline-offset-2"
      {...props}
    >
      {children}
    </a>
  );
}

/** Pass to <MessageResponse components={citationComponents}> so `#…-cite-N` links render as chips. */
export const citationComponents = { a: CitationLink };
