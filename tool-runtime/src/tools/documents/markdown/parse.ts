// Markdown to a small block tree. Only the lexer of `marked` is used; no HTML is ever rendered,
// links keep http, https and mailto only, images become their alt text and nothing here
// touches the network. The engines render this tree, never the markdown.
import { marked, type Token, type Tokens } from "marked";

export type Inline = {
  text: string;
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
  strike?: boolean;
  link?: string;
};
export type ListItem = { runs: Inline[]; children: Block[] };
export type Block =
  | { type: "heading"; level: 1 | 2 | 3; runs: Inline[] }
  | { type: "paragraph"; runs: Inline[] }
  | { type: "list"; ordered: boolean; start: number; items: ListItem[] }
  | {
      type: "table";
      header: Inline[][];
      rows: Inline[][][];
      align: ("left" | "center" | "right" | null)[];
    }
  | { type: "quote"; blocks: Block[] }
  | { type: "code"; text: string; language?: string }
  | { type: "hr" }
  | { type: "pagebreak" };

export const MAX_LIST_DEPTH = 4;
export const MAX_TABLE_COLUMNS = 16;
const SAFE_LINK = /^(https?:|mailto:)/i;
const PAGE_BREAK = /^\s*<!--\s*pagebreak\s*-->\s*$/i;

function decode(text: string): string {
  return text
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'");
}
function inline(tokens: Token[] | undefined, style: Omit<Inline, "text"> = {}): Inline[] {
  const runs: Inline[] = [];
  for (const token of tokens ?? []) {
    switch (token.type) {
      case "text":
      case "escape":
        runs.push({ ...style, text: decode(token.text) });
        break;
      case "strong":
        runs.push(...inline((token as Tokens.Strong).tokens, { ...style, bold: true }));
        break;
      case "em":
        runs.push(...inline((token as Tokens.Em).tokens, { ...style, italic: true }));
        break;
      case "del":
        runs.push(...inline((token as Tokens.Del).tokens, { ...style, strike: true }));
        break;
      case "codespan":
        runs.push({ ...style, text: decode((token as Tokens.Codespan).text), code: true });
        break;
      case "link": {
        const link = token as Tokens.Link;
        const href = SAFE_LINK.test(link.href) ? link.href : undefined;
        const inner = inline(link.tokens, href ? { ...style, link: href } : style);
        runs.push(...(inner.length ? inner : [{ ...style, text: decode(link.text), link: href }]));
        break;
      }
      case "image":
        runs.push({
          ...style,
          text: decode((token as Tokens.Image).text || "[bild]"),
          italic: true,
        });
        break;
      case "br":
        runs.push({ ...style, text: "\n" });
        break;
      case "html":
        runs.push({ ...style, text: decode((token as Tokens.HTML).text) });
        break;
      default:
        if ("text" in token && typeof token.text === "string")
          runs.push({ ...style, text: decode(token.text) });
    }
  }
  return runs;
}
function blocks(tokens: Token[], depth: number): Block[] {
  const out: Block[] = [];
  for (const token of tokens) {
    switch (token.type) {
      case "heading": {
        const heading = token as Tokens.Heading;
        out.push({
          type: "heading",
          level: Math.min(3, Math.max(1, heading.depth)) as 1 | 2 | 3,
          runs: inline(heading.tokens),
        });
        break;
      }
      case "paragraph":
        out.push({ type: "paragraph", runs: inline((token as Tokens.Paragraph).tokens) });
        break;
      case "text": {
        // Loose list items and blockquotes carry bare text tokens.
        const text = token as Tokens.Text;
        out.push({
          type: "paragraph",
          runs: text.tokens ? inline(text.tokens) : [{ text: decode(text.text) }],
        });
        break;
      }
      case "list": {
        const list = token as Tokens.List;
        const items: ListItem[] = list.items.map((item) => {
          const children = blocks(item.tokens, depth + 1);
          const runs: Inline[] = [];
          const rest: Block[] = [];
          for (const child of children) {
            if (child.type === "paragraph" && !runs.length) runs.push(...child.runs);
            else if (child.type === "list" && depth + 1 >= MAX_LIST_DEPTH)
              for (const nested of child.items) rest.push({ type: "paragraph", runs: nested.runs });
            else rest.push(child);
          }
          return { runs, children: rest };
        });
        out.push({
          type: "list",
          ordered: list.ordered,
          start: typeof list.start === "number" ? list.start : 1,
          items,
        });
        break;
      }
      case "table": {
        const table = token as Tokens.Table;
        const width = Math.min(table.header.length, MAX_TABLE_COLUMNS);
        out.push({
          type: "table",
          header: table.header.slice(0, width).map((cell) => inline(cell.tokens)),
          rows: table.rows.map((row) => row.slice(0, width).map((cell) => inline(cell.tokens))),
          align: table.align.slice(0, width),
        });
        break;
      }
      case "blockquote":
        out.push({ type: "quote", blocks: blocks((token as Tokens.Blockquote).tokens, depth + 1) });
        break;
      case "code":
        out.push({
          type: "code",
          text: (token as Tokens.Code).text,
          language: (token as Tokens.Code).lang || undefined,
        });
        break;
      case "hr":
        out.push({ type: "hr" });
        break;
      case "html": {
        const html = (token as Tokens.HTML).text;
        if (PAGE_BREAK.test(html)) out.push({ type: "pagebreak" });
        else if (html.trim()) out.push({ type: "paragraph", runs: [{ text: html.trim() }] });
        break;
      }
      case "space":
        break;
      default:
        if ("text" in token && typeof token.text === "string" && token.text.trim())
          out.push({ type: "paragraph", runs: [{ text: decode(token.text) }] });
    }
  }
  return out;
}
export function parseMarkdown(markdown: string): Block[] {
  const tokens = marked.lexer(markdown.replace(/\r\n?/g, "\n"), { gfm: true });
  return blocks(tokens, 0);
}
export function plainText(runs: Inline[]): string {
  return runs.map((r) => r.text).join("");
}
