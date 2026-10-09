// Runs inside sandbox children only. The Markdown block tree as semantic HTML for the PDF
// renderer: real headings, lists, tables with header cells, figures with alt text and
// captions, so the tagged PDF carries the same structure a screen reader gets from the Word
// file. Everything is escaped; the only URLs are the document's own image files and the
// http(s)/mailto links the parser admitted.
import type { Block, Inline } from "../markdown/parse";

/** One line of a page header or footer: text with page counters, aligned in its margin box. */
export type BandSegment = {
  align: "left" | "center" | "right";
  parts: (string | { counter: "page" | "pages" })[];
};
/** A page header or footer: its text segments and, for a header, the first picture it shows. */
export type Band = {
  segments: BandSegment[];
  logo?: { file: string; widthPt: number; heightPt: number };
};
/** An image file in the render directory, at the size it prints (points). */
export type HtmlImage = { file: string; caption?: string; widthPt: number; heightPt: number };

export type HtmlOptions = {
  title: string;
  /** BCP 47 tag, e.g. sv-SE. */
  language: string;
  author?: string;
  /** Whether the title leads the content as the document's first heading. */
  lead: boolean;
  images: Map<string, HtmlImage>;
  header?: Band;
  footer?: Band;
};

export function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inlines(runs: Inline[]): string {
  return runs
    .map((run) => {
      let html = escapeHtml(run.text).replaceAll("\n", "<br>");
      if (run.code) html = `<code>${html}</code>`;
      if (run.bold) html = `<strong>${html}</strong>`;
      if (run.italic) html = `<em>${html}</em>`;
      if (run.strike) html = `<s>${html}</s>`;
      if (run.link) html = `<a href="${escapeHtml(run.link)}">${html}</a>`;
      return html;
    })
    .join("");
}

function blocks(items: Block[], options: HtmlOptions, shift: number): string {
  return items.map((block) => one(block, options, shift)).join("\n");
}

function one(block: Block, options: HtmlOptions, shift: number): string {
  switch (block.type) {
    case "heading": {
      const level = Math.min(block.level + shift, 6);
      return `<h${level}>${inlines(block.runs)}</h${level}>`;
    }
    case "paragraph":
      return `<p>${inlines(block.runs)}</p>`;
    case "list": {
      const tag = block.ordered ? "ol" : "ul";
      const start = block.ordered && block.start !== 1 ? ` start="${block.start}"` : "";
      const items = block.items
        .map(
          (item) =>
            `<li>${inlines(item.runs)}${
              item.children.length ? `\n${blocks(item.children, options, shift)}\n` : ""
            }</li>`,
        )
        .join("\n");
      return `<${tag}${start}>\n${items}\n</${tag}>`;
    }
    case "table": {
      const style = (index: number) => {
        const align = block.align[index];
        return align && align !== "left" ? ` style="text-align:${align}"` : "";
      };
      const header = block.header
        .map((cell, index) => `<th scope="col"${style(index)}>${inlines(cell)}</th>`)
        .join("");
      const rows = block.rows
        .map(
          (row) =>
            `<tr>${row.map((cell, index) => `<td${style(index)}>${inlines(cell)}</td>`).join("")}</tr>`,
        )
        .join("\n");
      return `<table>\n<thead><tr>${header}</tr></thead>\n<tbody>\n${rows}\n</tbody>\n</table>`;
    }
    case "quote":
      return `<blockquote>\n${blocks(block.blocks, options, shift)}\n</blockquote>`;
    case "code": {
      const language =
        block.language && /^[\w+-]{1,30}$/.test(block.language)
          ? ` class="language-${block.language}"`
          : "";
      return `<pre><code${language}>${escapeHtml(block.text)}</code></pre>`;
    }
    case "hr":
      return "<hr>";
    case "pagebreak":
      return '<div class="page-break" aria-hidden="true"></div>';
    case "image": {
      const image = options.images.get(block.id);
      if (!image) return "";
      const alt = escapeHtml(block.alt || image.caption || "");
      const caption = image.caption
        ? `\n<figcaption>${escapeHtml(image.caption)}</figcaption>`
        : "";
      return `<figure>\n<img src="${escapeHtml(image.file)}" alt="${alt}" style="width:${image.widthPt.toFixed(1)}pt;height:${image.heightPt.toFixed(1)}pt">${caption}\n</figure>`;
    }
  }
}

function band(id: string, band: Band | undefined): string {
  if (!band || (!band.segments.length && !band.logo)) return "";
  const segments = band.segments
    .map(
      (segment) =>
        `<span class="band-${segment.align}">${segment.parts
          .map((part) =>
            typeof part === "string"
              ? escapeHtml(part)
              : `<span class="counter-${part.counter}"></span>`,
          )
          .join("")}</span>`,
    )
    .join("");
  const logo = band.logo
    ? `<img class="band-logo" src="${escapeHtml(band.logo.file)}" alt="" style="width:${band.logo.widthPt}pt;height:${band.logo.heightPt}pt">`
    : "";
  return `<div id="${id}" class="band">${logo}${segments}</div>`;
}

/** The smallest heading level the blocks use, at any depth. */
function minHeadingLevel(items: Block[]): number | undefined {
  let min: number | undefined;
  for (const block of items) {
    const level =
      block.type === "heading"
        ? block.level
        : block.type === "quote"
          ? minHeadingLevel(block.blocks)
          : block.type === "list"
            ? block.items.map((item) => minHeadingLevel(item.children)).find((l) => l !== undefined)
            : undefined;
    if (level !== undefined && (min === undefined || level < min)) min = level;
  }
  return min;
}

/** The whole document as an HTML page the PDF renderer lays out. */
export function renderHtml(content: Block[], options: HtmlOptions): string {
  // Under a leading title (the h1), the content's highest heading becomes h2, so the
  // outline never skips a level, as accessibility checkers require.
  const shift = options.lead ? 2 - (minHeadingLevel(content) ?? 2) : 0;
  const title = options.lead ? `<h1 class="title">${escapeHtml(options.title)}</h1>\n` : "";
  return `<!DOCTYPE html>
<html lang="${escapeHtml(options.language)}">
<head>
<meta charset="utf-8">
<title>${escapeHtml(options.title)}</title>
${options.author ? `<meta name="author" content="${escapeHtml(options.author)}">\n` : ""}<meta name="generator" content="Eneo">
<link rel="stylesheet" href="document.css">
</head>
<body>
${band("page-header", options.header)}
${band("page-footer", options.footer)}
<main class="document">
${title}${blocks(content, options, shift)}
</main>
</body>
</html>
`;
}
