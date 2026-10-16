import type { Extensions } from "@tiptap/core";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import { TableKit } from "@tiptap/extension-table";
import { Markdown, MarkdownManager } from "@tiptap/markdown";
import StarterKit from "@tiptap/starter-kit";
import { DocumentCodeBlock } from "./codeBlock";
import { EneoImage } from "./eneoImage";
import { PageBreak } from "./pageBreak";
import { PassageHighlight } from "./passageHighlight";
import { RawHtml } from "./rawHtml";

export type DocumentExtensionOptions = {
  /** A link the reader may load the file an image handle names from. */
  resolveImage?: (fileId: string) => Promise<string | undefined>;
  /** What a page break is called. */
  pageBreakLabel?: string;
};

// The Markdown the document tools write and read back: GFM, and no line break
// on a single newline.
const MARKED_OPTIONS = { gfm: true, breaks: false } as const;

// Only web and mail links reach the page; anything else stays as text.
const LINK_PROTOCOLS = ["http", "https", "mailto"];
const isAllowedHref = (href: string) => /^(https?:|mailto:)/i.test(href);

/**
 * The document model of a generated Markdown document: what the document
 * tools can write (see their `content` description), no more. Framework
 * independent, so the same list serves an editor and a headless converter.
 */
export function documentExtensions({
  resolveImage,
  pageBreakLabel = ""
}: DocumentExtensionOptions = {}): Extensions {
  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3] },
      underline: false,
      link: {
        openOnClick: false,
        autolink: false,
        linkOnPaste: false,
        protocols: LINK_PROTOCOLS,
        isAllowedUri: (url, context) => context.defaultValidate(url) && isAllowedHref(url),
        shouldAutoLink: () => false
      },
      // Replaced by the highlighted code block below.
      codeBlock: false
    }),
    DocumentCodeBlock,
    TableKit.configure({ table: { resizable: false } }),
    TaskList,
    TaskItem.configure({ nested: true }),
    EneoImage.configure({ resolveImage }),
    PageBreak.configure({ label: pageBreakLabel }),
    ...RawHtml,
    PassageHighlight,
    Markdown.configure({ markedOptions: MARKED_OPTIONS })
  ];
}

/** Markdown as the document tools write it: ending in a newline. */
export const withFinalNewline = (markdown: string) =>
  markdown.endsWith("\n") ? markdown : `${markdown}\n`;

/** Converts between Markdown and the document model without an editor. */
export function documentMarkdown(options: DocumentExtensionOptions = {}) {
  return new MarkdownManager({
    extensions: documentExtensions(options),
    markedOptions: MARKED_OPTIONS
  });
}
