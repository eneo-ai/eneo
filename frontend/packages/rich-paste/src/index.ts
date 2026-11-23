/**
 * Formatted text from the clipboard as Markdown.
 *
 * The chat composers hold plain text, so a paste from Word or a web page used
 * to lose its link addresses, headings, lists and emphasis. Markdown keeps
 * them in a form the model reads and the person can still edit.
 *
 * The HTML is parsed into an inert document (no scripts run, nothing loads)
 * and only text comes out. Nothing is escaped: the result is read by a person
 * and a model, not by a renderer.
 */

/** Above this the paste falls back to the clipboard's plain text. */
const MAX_HTML_CHARS = 2_000_000;

const INDENT = "    ";

const SKIPPED = new Set([
  "SCRIPT",
  "STYLE",
  "HEAD",
  "META",
  "LINK",
  "TITLE",
  "TEMPLATE",
  "NOSCRIPT",
  "IMG",
  "PICTURE",
  "SVG",
  "CANVAS",
  "VIDEO",
  "AUDIO",
  "IFRAME",
  "OBJECT",
  "BUTTON",
  "INPUT",
  "SELECT",
  "TEXTAREA",
]);

const BLOCK_TAGS = [
  "ADDRESS",
  "ARTICLE",
  "ASIDE",
  "BLOCKQUOTE",
  "CENTER",
  "DD",
  "DETAILS",
  "DIV",
  "DL",
  "DT",
  "FIELDSET",
  "FIGCAPTION",
  "FIGURE",
  "FOOTER",
  "FORM",
  "H1",
  "H2",
  "H3",
  "H4",
  "H5",
  "H6",
  "HEADER",
  "HR",
  "LI",
  "MAIN",
  "NAV",
  "OL",
  "P",
  "PRE",
  "SECTION",
  "SUMMARY",
  "TABLE",
  "TBODY",
  "TD",
  "TFOOT",
  "TH",
  "THEAD",
  "TR",
  "UL",
];
const BLOCKS = new Set(BLOCK_TAGS);
const BLOCK_SELECTOR = BLOCK_TAGS.join(",");

type Context = {
  /** Set once something is written that plain text could not have carried. */
  rich: boolean;
  /** Emphasis is left out where it would be noise (inside a heading). */
  marks: boolean;
  bold: boolean;
  italic: boolean;
};

type Block = { text: string; listItem?: boolean };

/**
 * Markdown for a clipboard's HTML, or null when the HTML carries nothing that
 * its plain text lacks (the caller then pastes the plain text as before).
 */
export function htmlToMarkdown(html: string): string | null {
  if (!html || html.length > MAX_HTML_CHARS) return null;
  const body = parse(html);
  if (!body) return null;
  const context: Context = {
    rich: false,
    marks: true,
    bold: false,
    italic: false,
  };
  const markdown = join(blocks(body.childNodes, context, 0));
  return context.rich && markdown ? markdown : null;
}

/** Whether a clipboard's HTML holds any text (and not just a picture). */
export function htmlHasText(html: string): boolean {
  if (!html) return false;
  if (html.length > MAX_HTML_CHARS) return true;
  const body = parse(html);
  if (!body) return false;
  for (const element of body.querySelectorAll("script,style,template")) {
    element.remove();
  }
  return (body.textContent ?? "").trim() !== "";
}

type Clipboard = Pick<DataTransfer, "getData">;

/** `htmlToMarkdown` for a paste event's clipboard. */
export function clipboardMarkdown(clipboard: Clipboard | null): string | null {
  return clipboard ? htmlToMarkdown(clipboard.getData("text/html")) : null;
}

/**
 * Whether a paste is text. Word processors and spreadsheets put a picture of
 * the selection on the clipboard beside the text; a composer that attaches pasted files uses
 * this to leave that picture out.
 */
export function clipboardHasFormattedText(
  clipboard: Clipboard | null,
): boolean {
  return clipboard ? htmlHasText(clipboard.getData("text/html")) : false;
}

function parse(html: string): HTMLElement | null {
  if (typeof DOMParser === "undefined") return null;
  return new DOMParser().parseFromString(html, "text/html").body;
}

function join(parts: Block[]): string {
  let out = "";
  let previous: Block | undefined;
  for (const part of parts) {
    if (previous) out += previous.listItem && part.listItem ? "\n" : "\n\n";
    out += part.text;
    previous = part;
  }
  return out;
}

function isElement(node: Node): node is Element {
  return node.nodeType === 1;
}

function styleOf(element: Element): string {
  return element.getAttribute("style") ?? "";
}

function hasBlockContent(element: Element): boolean {
  return (
    BLOCKS.has(element.tagName) ||
    element.querySelector(BLOCK_SELECTOR) !== null
  );
}

/** Trims every line, collapses runs of spaces and drops blank edge lines. */
function tidy(text: string): string {
  return text
    .split("\n")
    .map((line) => line.replace(/[ \t ]+/g, " ").trim())
    .join("\n")
    .replace(/^\n+|\n+$/g, "")
    .replace(/\n{3,}/g, "\n\n");
}

function blocks(
  nodes: Iterable<Node>,
  context: Context,
  depth: number,
): Block[] {
  const out: Block[] = [];
  let run = "";
  const flush = () => {
    const text = tidy(run);
    if (text) out.push({ text });
    run = "";
  };

  for (const node of nodes) {
    if (!isElement(node)) {
      if (node.nodeType === 3) run += inline(node, context);
      continue;
    }
    const tag = node.tagName;
    if (SKIPPED.has(tag) || /display:\s*none/i.test(styleOf(node))) continue;
    if (!hasBlockContent(node)) {
      run += inline(node, context);
      continue;
    }
    flush();

    const wordItem = tag === "P" ? wordListItem(node, context) : null;
    if (wordItem) {
      out.push(wordItem);
    } else if (/^H[1-6]$/.test(tag)) {
      const text = tidy(inline(node, { ...context, marks: false }, true));
      if (text) {
        context.rich = true;
        out.push({
          text: `${"#".repeat(Number(tag[1]))} ${text.replace(/\n+/g, " ")}`,
        });
      }
    } else if (tag === "UL" || tag === "OL") {
      const text = list(node, context, depth);
      if (text) out.push({ text, listItem: true });
    } else if (tag === "BLOCKQUOTE") {
      const text = join(blocks(node.childNodes, context, depth));
      if (text) {
        context.rich = true;
        out.push({ text: text.replace(/^/gm, "> ").replace(/^> $/gm, ">") });
      }
    } else if (tag === "PRE") {
      const text = (node.textContent ?? "").replace(/^\n+|\s+$/g, "");
      if (text) {
        context.rich = true;
        out.push({ text: `\`\`\`\n${text}\n\`\`\`` });
      }
    } else if (tag === "TABLE") {
      out.push(...table(node, context, depth));
    } else if (tag === "HR") {
      out.push({ text: "---" });
    } else {
      out.push(...blocks(node.childNodes, context, depth));
    }
  }
  flush();
  return out;
}

function list(element: Element, context: Context, depth: number): string {
  const ordered = element.tagName === "OL";
  let number = Number(element.getAttribute("start")) || 1;
  const lines: string[] = [];
  for (const child of element.children) {
    // Some editors nest a list directly in a list, not in the item above it.
    if (child.tagName === "UL" || child.tagName === "OL") {
      const nested = list(child, context, depth + 1);
      if (nested) lines.push(nested);
      continue;
    }
    if (child.tagName !== "LI") continue;
    const own: Node[] = [];
    const nested: string[] = [];
    for (const node of child.childNodes) {
      if (isElement(node) && (node.tagName === "UL" || node.tagName === "OL")) {
        const text = list(node, context, depth + 1);
        if (text) nested.push(text);
      } else {
        own.push(node);
      }
    }
    const text = blocks(own, context, depth)
      .map((block) => block.text)
      .join("\n");
    if (text || nested.length > 0) {
      const marker = ordered ? `${number++}.` : "-";
      lines.push(listLine(marker, text, depth), ...nested);
    }
  }
  if (lines.length > 0) context.rich = true;
  return lines.join("\n");
}

function listLine(marker: string, text: string, depth: number): string {
  const indent = INDENT.repeat(depth);
  return `${indent}${marker} ${text.replace(/\n/g, `\n${indent}${INDENT}`)}`;
}

/**
 * Word writes a list as paragraphs: the level is in the `mso-list` style and
 * the bullet or number is a span of its own, marked to be ignored.
 */
function wordListItem(paragraph: Element, context: Context): Block | null {
  const level = /mso-list:[^;"']*level(\d+)/i.exec(styleOf(paragraph));
  if (!level) return null;
  let marker = "";
  for (const span of paragraph.querySelectorAll("[style]")) {
    if (/mso-list:\s*ignore/i.test(styleOf(span))) {
      marker = (span.textContent ?? "").trim();
      span.remove();
      break;
    }
  }
  const text = tidy(inline(paragraph, context, true)).replace(/\n+/g, " ");
  if (!text) return null;
  context.rich = true;
  const number = /^\(?(\d+)[.)]$/.exec(marker);
  const lettered = /^\(?[a-zA-Z]{1,4}[.)]$/.test(marker);
  const sign = number ? `${number[1]}.` : lettered ? "1." : "-";
  return { text: listLine(sign, text, Number(level[1]) - 1), listItem: true };
}

function table(element: Element, context: Context, depth: number): Block[] {
  const rows = [...element.querySelectorAll("tr")].filter(
    (row) => row.closest("table") === element,
  );
  const cells = rows.map((row) =>
    [...row.children].filter(
      (cell) => cell.tagName === "TD" || cell.tagName === "TH",
    ),
  );
  const columns = Math.max(0, ...cells.map((row) => row.length));
  // A table used for page layout is read as the content it holds.
  const layout =
    columns < 2 ||
    cells.some((row) => row.some((cell) => cell.querySelector("table,ul,ol")));
  if (layout) {
    return cells.flatMap((row) =>
      row.flatMap((cell) => blocks(cell.childNodes, context, depth)),
    );
  }
  const lines = cells
    .map((row) =>
      row.map((cell) =>
        tidy(inline(cell, context, true))
          .replace(/\n+/g, " ")
          .replace(/\|/g, "\\|"),
      ),
    )
    .filter((row) => row.some((text) => text !== ""))
    .map((row) => {
      const padded = [...row, ...Array(columns - row.length).fill("")];
      return `| ${padded.join(" | ")} |`;
    });
  if (lines.length === 0) return [];
  context.rich = true;
  lines.splice(1, 0, `|${" --- |".repeat(columns)}`);
  return [{ text: lines.join("\n") }];
}

function linkTarget(element: Element): string | null {
  const href = (element.getAttribute("href") ?? "").trim();
  if (!/^(https?:\/\/|mailto:)/i.test(href)) return null;
  return href.replace(
    /[\s()<>]/g,
    (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

function sameAddress(text: string, target: string): boolean {
  const bare = (value: string) =>
    value.replace(/^(https?:\/\/|mailto:)/i, "").replace(/\/$/, "");
  return bare(text) === bare(target);
}

/** Puts the marker inside the surrounding spaces, on each line of its own. */
function mark(marker: string, text: string): string {
  return text
    .split("\n")
    .map((line) => {
      const parts = /^(\s*)(.*?)(\s*)$/.exec(line);
      if (!parts || !parts[2]) return line;
      return `${parts[1]}${marker}${parts[2]}${marker}${parts[3]}`;
    })
    .join("\n");
}

function weight(element: Element): "bold" | "normal" | null {
  const value = /font-weight:\s*([a-z0-9]+)/i.exec(styleOf(element))?.[1];
  if (!value) return null;
  if (/^(bold|bolder)$/i.test(value) || Number(value) >= 600) return "bold";
  return "normal";
}

/**
 * The text of a node with its links and emphasis. `children` renders only what
 * is inside the node, for a block whose own tag has been handled.
 */
function inline(node: Node, context: Context, children = false): string {
  if (node.nodeType === 3) return (node.nodeValue ?? "").replace(/\s+/g, " ");
  if (!isElement(node)) return "";
  const inner = (next: Context = context) => {
    let text = "";
    for (const child of node.childNodes) text += inline(child, next);
    if (next !== context && next.rich) context.rich = true;
    return text;
  };
  if (children) return inner();

  const tag = node.tagName;
  if (SKIPPED.has(tag) || /display:\s*none/i.test(styleOf(node))) return "";
  if (tag === "BR") return "\n";
  if (BLOCKS.has(tag)) return `\n${inner()}\n`;

  if (tag === "A") {
    const text = tidy(inner()).replace(/\n+/g, " ");
    const target = linkTarget(node);
    if (!text || !target) return text;
    context.rich = true;
    return sameAddress(text, target) ? target : `[${text}](${target})`;
  }
  if (tag === "CODE" || tag === "KBD" || tag === "SAMP") {
    const text = node.textContent ?? "";
    if (!text.trim()) return text;
    context.rich = true;
    return `\`${text}\``;
  }
  if (!context.marks) return inner();

  // Some online editors wrap a whole paste in <b style="font-weight:normal">
  // and mark real emphasis with styled spans, so the style has the last word.
  const weighted = weight(node);
  const bold =
    !context.bold &&
    (weighted === "bold" ||
      ((tag === "B" || tag === "STRONG") && weighted !== "normal"));
  const italic =
    !context.italic &&
    (tag === "I" ||
      tag === "EM" ||
      /font-style:\s*italic/i.test(styleOf(node)));
  const struck = tag === "S" || tag === "DEL" || tag === "STRIKE";

  let text = inner({
    ...context,
    rich: false,
    bold: context.bold || bold,
    italic: context.italic || italic,
  });
  if (!text.trim()) return text;
  if (struck) text = mark("~~", text);
  if (italic) text = mark("*", text);
  if (bold) text = mark("**", text);
  if (bold || italic || struck) context.rich = true;
  return text;
}
