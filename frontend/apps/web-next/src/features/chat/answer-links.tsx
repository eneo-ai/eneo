"use client";

import { useTranslations } from "next-intl";
import { createContext, useContext, useMemo, type ComponentProps, type ReactNode } from "react";
import { citationComponents } from "@/components/ai-elements/citation";
import type { GeneratedDocument } from "./side-panel/document-versions";

/**
 * Document names in an answer. A remark plugin turns every mention of a
 * document the conversation holds ("se Projektplan") into a `#eneo-doc-N`
 * link node, N indexing the names it was given, and the `a` component
 * override renders exactly those as buttons that open the document in the
 * side panel. Every other link falls through to the citation link, which
 * handles `#…-cite-N` chips and plain links.
 */

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] };

const DOC_LINK = /^#eneo-doc-(\d{1,3})$/;

function splitNames(value: string, names: string[]): MdNode[] {
  const out: MdNode[] = [];
  let rest = value;
  while (rest) {
    let best: { index: number; at: number } | null = null;
    for (const [index, name] of names.entries()) {
      const at = rest.indexOf(name);
      if (at === -1) continue;
      // The earliest mention wins; at the same place the longest name does.
      if (!best || at < best.at || (at === best.at && name.length > names[best.index]!.length)) {
        best = { index, at };
      }
    }
    if (!best) break;
    const name = names[best.index]!;
    if (best.at > 0) out.push({ type: "text", value: rest.slice(0, best.at) });
    out.push({
      type: "link",
      url: `#eneo-doc-${best.index}`,
      children: [{ type: "text", value: name }]
    });
    rest = rest.slice(best.at + name.length);
  }
  if (out.length === 0) return [{ type: "text", value }];
  if (rest) out.push({ type: "text", value: rest });
  return out;
}

function transform(node: MdNode, names: string[]) {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === "text" && child.value) {
      next.push(...splitNames(child.value, names));
    } else {
      // Code and existing links keep their text as it is.
      if (child.type !== "code" && child.type !== "inlineCode" && child.type !== "link") {
        transform(child, names);
      }
      next.push(child);
    }
  }
  node.children = next;
}

type DocumentNamesOptions = { names: string[] };

function documentNamesRemark({ names }: DocumentNamesOptions) {
  return (tree: MdNode) => {
    if (names.length > 0) transform(tree, names);
  };
}

/** The names an answer can mention a document by, longest first so a longer name wins. */
export function documentNames(documents: readonly GeneratedDocument[]): string[] {
  const names = new Set<string>();
  for (const document of documents) {
    names.add(document.name);
    // A Markdown document is read in Eneo and goes by its title.
    const title = document.name.replace(/\.(md|markdown)$/i, "");
    if (title.length >= 3) names.add(title);
  }
  return [...names].sort((a, b) => b.length - a.length);
}

type DocumentNamesPlugin = [typeof documentNamesRemark, DocumentNamesOptions];

/** The remark plugin list that links document names, stable while the names are. */
export function useDocumentNameRemarkPlugins(names: string[]): DocumentNamesPlugin[] {
  const key = names.join("\u0000");
  // Streamdown caches processors by plugin name and serialized options, so
  // the same names give the same processor.
  return useMemo(
    () => (names.length > 0 ? [[documentNamesRemark, { names }]] : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the names are compared by content
    [key]
  );
}

type DocumentLinksValue = {
  names: string[];
  /** The document a name stands for: the newest version of that name. */
  fileFor: (name: string) => GeneratedDocument | undefined;
  onOpen: (file: GeneratedDocument, trigger: HTMLElement) => void;
};

const DocumentLinksContext = createContext<DocumentLinksValue | null>(null);

export function DocumentLinksProvider({
  value,
  children
}: {
  value: DocumentLinksValue;
  children: ReactNode;
}) {
  return <DocumentLinksContext.Provider value={value}>{children}</DocumentLinksContext.Provider>;
}

const CitationLink = citationComponents.a;

/** An answer's link: a document name opens the document, anything else is a citation or a plain link. */
export function AnswerLink(props: ComponentProps<"a"> & { node?: unknown }) {
  const t = useTranslations();
  const links = useContext(DocumentLinksContext);
  const match = typeof props.href === "string" ? DOC_LINK.exec(props.href) : null;
  const name = match && links ? links.names[Number(match[1])] : undefined;
  const file = name ? links?.fileFor(name) : undefined;
  if (file && links) {
    return (
      <button
        type="button"
        aria-label={t("file_preview_open", { name: file.name })}
        onClick={(event) => links.onOpen(file, event.currentTarget)}
        className="text-ax-text-accent focus-visible:outline-ring rounded-ax-inner font-[inherit] underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {props.children}
      </button>
    );
  }
  if (match) return <>{props.children}</>;
  return <CitationLink {...props} />;
}

/** Pass to <MessageResponse components={answerLinkComponents}>: document names and citations as controls. */
export const answerLinkComponents = { a: AnswerLink };
