"use client";

import { ScrollableArea } from "@astryxdesign/core/ScrollableArea";
import { useTranslations } from "next-intl";
import { useMemo, type ComponentProps } from "react";
import type { StreamdownTranslations } from "streamdown";
import { cn } from "@/lib/utils";

/**
 * Eneo overrides for Streamdown's markdown elements (assistant answers, MCP
 * snippets). They exist for WCAG 2.2 AA (ACCESSIBILITY.md → AI chat):
 *
 * - Tables sit in a bordered Astryx ScrollableArea: a named region that joins
 *   the tab order only when the table actually overflows (2.1.1), with
 *   `<th scope="col">` header cells (1.3.1).
 * - Headings start at h3 so they nest under the page's h1 and the
 *   conversation (1.3.1, 2.4.6): markdown `#`/`##` → h3, `###` → h4, …
 * - Lists keep visible numbers/bullets (the Astryx reset removes list styles).
 * - Code blocks become named, focusable scroll regions (rehype plugin below).
 */

type MarkdownProps<Tag extends keyof React.JSX.IntrinsicElements> = ComponentProps<Tag> & {
  node?: unknown;
};

function MarkdownTable({ children, className, node: _node, ...props }: MarkdownProps<"table">) {
  const t = useTranslations();
  return (
    <ScrollableArea
      axis="inline"
      role="region"
      label={t("chat_md_table_label")}
      className="border-ax-border focus-visible:outline-ring rounded-ax-container my-4 border font-sans focus-visible:outline-2 focus-visible:outline-offset-2"
    >
      <table
        className={cn("w-full border-collapse text-left text-[13.5px] leading-snug", className)}
        {...props}
      >
        {children}
      </table>
    </ScrollableArea>
  );
}

function MarkdownThead({ children, className, node: _node, ...props }: MarkdownProps<"thead">) {
  return (
    <thead className={cn("bg-ax-muted", className)} {...props}>
      {children}
    </thead>
  );
}

function MarkdownTr({ children, className, node: _node, ...props }: MarkdownProps<"tr">) {
  return (
    <tr className={cn("border-ax-border border-t first:border-t-0", className)} {...props}>
      {children}
    </tr>
  );
}

function MarkdownTh({ children, className, node: _node, ...props }: MarkdownProps<"th">) {
  return (
    <th
      scope="col"
      className={cn(
        "text-ax-text-secondary px-3.5 py-2 align-bottom text-[12.5px] font-semibold",
        className
      )}
      {...props}
    >
      {children}
    </th>
  );
}

function MarkdownTd({ children, className, node: _node, ...props }: MarkdownProps<"td">) {
  return (
    <td className={cn("px-3.5 py-2 align-top", className)} {...props}>
      {children}
    </td>
  );
}

function MarkdownOl({ children, className, node: _node, ...props }: MarkdownProps<"ol">) {
  return (
    <ol className={cn("my-3 list-outside list-decimal ps-6", className)} {...props}>
      {children}
    </ol>
  );
}

function MarkdownUl({ children, className, node: _node, ...props }: MarkdownProps<"ul">) {
  return (
    <ul className={cn("my-3 list-outside list-disc ps-6", className)} {...props}>
      {children}
    </ul>
  );
}

function MarkdownLi({ children, className, node: _node, ...props }: MarkdownProps<"li">) {
  return (
    <li className={cn("my-1 ps-1", className)} {...props}>
      {children}
    </li>
  );
}

/** Markdown depth → rendered level: the answer's top headings are h3. */
export function answerHeadingLevel(depth: number): 3 | 4 | 5 | 6 {
  if (depth <= 2) return 3;
  return Math.min(depth + 1, 6) as 4 | 5 | 6;
}

const HEADING_CLASS: Record<3 | 4 | 5 | 6, string> = {
  3: "mt-5 mb-2 font-sans text-[15px] leading-snug font-bold",
  4: "mt-4 mb-1.5 font-sans text-[14px] leading-snug font-semibold",
  5: "mt-3 mb-1 font-sans text-[13.5px] leading-snug font-semibold",
  6: "mt-3 mb-1 font-sans text-[13px] leading-snug font-semibold"
};

function heading(depth: number) {
  const level = answerHeadingLevel(depth);
  const Tag = `h${level}` as const;
  function MarkdownHeading({ children, className, node: _node, ...props }: MarkdownProps<"h3">) {
    return (
      <Tag className={cn(HEADING_CLASS[level], className)} {...props}>
        {children}
      </Tag>
    );
  }
  MarkdownHeading.displayName = `MarkdownHeading${depth}`;
  return MarkdownHeading;
}

export const markdownComponents = {
  table: MarkdownTable,
  thead: MarkdownThead,
  tr: MarkdownTr,
  th: MarkdownTh,
  td: MarkdownTd,
  ol: MarkdownOl,
  ul: MarkdownUl,
  li: MarkdownLi,
  h1: heading(1),
  h2: heading(2),
  h3: heading(3),
  h4: heading(4),
  h5: heading(5),
  h6: heading(6)
};

type HastNode = {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

function codeLanguage(node: HastNode): string | null {
  const classes = node.properties?.className;
  const list = Array.isArray(classes) ? classes : typeof classes === "string" ? [classes] : [];
  for (const entry of list) {
    if (typeof entry === "string" && entry.startsWith("language-")) {
      return entry.slice("language-".length) || null;
    }
  }
  return null;
}

// Class names flow from the code element onto Streamdown's scroll body; listed
// here verbatim so Tailwind emits them.
const CODE_REGION_FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

/**
 * Rehype plugin: marks every fenced code block as a named, focusable scroll
 * region (ACCESSIBILITY.md rule 2). Streamdown forwards the code element's
 * extra properties to its scrolling code body. Runs after Streamdown's
 * sanitizer, so the attributes survive.
 */
export function rehypeCodeBlockRegions(label: (language: string | null) => string) {
  return () => (tree: HastNode) => {
    const visit = (node: HastNode, parent: HastNode | null) => {
      if (node.type === "element" && node.tagName === "code" && parent?.tagName === "pre") {
        const language = codeLanguage(node);
        const classes = node.properties?.className;
        node.properties = {
          ...node.properties,
          className: [...(Array.isArray(classes) ? classes : []), ...CODE_REGION_FOCUS.split(" ")],
          role: "region",
          tabIndex: 0,
          ariaLabel: label(language)
        };
      }
      for (const child of node.children ?? []) visit(child, node);
    };
    visit(tree, null);
  };
}

/**
 * Streamdown's own UI strings (copy/download buttons, diagram controls) in the
 * user's language. Memoized on `t`: Streamdown re-renders every block when the
 * object identity changes.
 */
export function useStreamdownTranslations(): Partial<StreamdownTranslations> {
  const t = useTranslations();
  return useMemo(
    () => ({
      close: t("close"),
      copied: t("copied"),
      copyCode: t("chat_md_copy_code"),
      copyLink: t("chat_md_copy_link"),
      downloadFile: t("chat_md_download_file"),
      downloadImage: t("chat_md_download_image"),
      downloadDiagram: t("chat_md_download_diagram"),
      downloadDiagramAsSvg: t("chat_md_download_diagram"),
      downloadDiagramAsPng: t("chat_md_download_diagram"),
      downloadDiagramAsMmd: t("chat_md_download_diagram"),
      imageNotAvailable: t("chat_md_image_unavailable"),
      viewFullscreen: t("chat_md_fullscreen"),
      exitFullscreen: t("chat_md_exit_fullscreen"),
      zoomIn: t("chat_md_zoom_in"),
      zoomOut: t("chat_md_zoom_out"),
      resetView: t("chat_md_reset_view"),
      openLink: t("chat_md_open_link"),
      openExternalLink: t("chat_md_open_link")
    }),
    [t]
  );
}
