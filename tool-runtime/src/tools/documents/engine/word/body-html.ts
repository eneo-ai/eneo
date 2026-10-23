// Runs inside sandbox children only. The template's own body as HTML for the PDF: the
// paragraphs, tables and pictures the template keeps around its content placeholder, with
// their placeholders already filled, so a PDF carries the same fixed text as the Word file.
// The body comes from a Word rendering made with marker strings for the title and the
// content; the content itself is rendered from Markdown (html.ts) and spliced in at its
// marker, and the title marker takes the document's title where the template put it.
import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import { escapeHtml } from "../html";
import { relationEntries } from "../pdf-profile";
import { parsedPart, type StyleMap, type Zip } from "./inspect";
import { at, attr, children, find, rootElement, walk, type Element } from "./ooxml";

/** The template body around the content: HTML before and after it. */
export type TemplateBody = {
  before: string;
  after: string;
  /** Whether the body shows the document's title, so the content needs no title of its own. */
  hasTitle: boolean;
};

export type BodyMarkers = { content: string; title: string };
const EMU_PER_PT = 12700;
const MAX_PICTURES = 20;

type Context = {
  zip: Zip;
  styles: StyleMap;
  markers: BodyMarkers;
  title: string;
  rels: Map<string, { target: string; external: boolean }>;
  assetsDir: string;
  pictures: number;
  hasTitle: boolean;
};

function onOff(node: Element | undefined): boolean {
  if (!node) return false;
  const value = attr(node, "w:val");
  return value === undefined || !["0", "false", "off"].includes(value);
}

function paragraphStyle(paragraph: Element): string | undefined {
  return attr(at(paragraph, "w:pPr", "w:pStyle"), "w:val");
}

/** The heading tag for a paragraph style: the title, a heading level, or a plain paragraph. */
function tagFor(styleId: string | undefined, styles: StyleMap): string {
  if (!styleId) return "p";
  if (styleId === styles.title || styleId === "Title") return "h1 class=\"title\"";
  const level = styles.heading.findIndex((id, index) => index > 0 && id === styleId);
  if (level > 0) return `h${Math.min(level, 6)}`;
  if (/^Heading(\d)$/.test(styleId)) return `h${Math.min(Number(styleId.slice(7)), 6)}`;
  return "p";
}

async function picture(context: Context, drawing: Element): Promise<string> {
  if (context.pictures >= MAX_PICTURES) return "";
  let embed: string | undefined;
  let cx = 0;
  let cy = 0;
  let alt = "";
  walk(drawing, (node) => {
    if (node.name === "wp:extent" && !cx) {
      cx = Number(attr(node, "cx") ?? 0);
      cy = Number(attr(node, "cy") ?? 0);
    }
    if (node.name === "wp:docPr" && !alt) alt = attr(node, "descr") ?? attr(node, "title") ?? "";
    if (node.name === "a:blip" && !embed) embed = attr(node, "r:embed");
  });
  const relation = embed && context.rels.get(embed);
  if (!relation || relation.external || !cx || !cy) return "";
  const target = relation.target;
  const mediaName = target.startsWith("/") ? target.slice(1) : `word/${target}`;
  const extension = /\.(png|jpe?g)$/i.exec(mediaName)?.[1]?.toLowerCase();
  const bytes = extension && (await context.zip.file(mediaName)?.async("nodebuffer"));
  if (!bytes) return "";
  const file = `body-${context.pictures++}.${extension === "jpeg" ? "jpg" : extension}`;
  await writeFile(join(context.assetsDir, file), bytes, { mode: 0o600 });
  const width = (cx / EMU_PER_PT).toFixed(1);
  const height = (cy / EMU_PER_PT).toFixed(1);
  return `<img src="${file}" alt="${escapeHtml(alt)}" style="width:${width}pt;height:${height}pt">`;
}

/** The runs of a paragraph (or an inline control, hyperlink or field) as inline HTML. */
async function inlines(context: Context, node: Element): Promise<string> {
  let html = "";
  for (const child of children(node)) {
    if (child.type !== "element") continue;
    switch (child.name) {
      case "w:r": {
        const properties = find(child, "w:rPr");
        let text = "";
        for (const piece of children(child)) {
          if (piece.type !== "element") continue;
          if (piece.name === "w:t")
            text += escapeHtml(
              children(piece)
                .map((t) => String(t.text ?? ""))
                .join(""),
            );
          else if (piece.name === "w:tab") text += " ";
          else if (piece.name === "w:br" || piece.name === "w:cr") text += "<br>";
          else if (piece.name === "w:drawing") text += await picture(context, piece);
        }
        if (!text) break;
        if (onOff(find(properties, "w:b"))) text = `<strong>${text}</strong>`;
        if (onOff(find(properties, "w:i"))) text = `<em>${text}</em>`;
        html += text;
        break;
      }
      case "w:hyperlink": {
        const inner = await inlines(context, child);
        const relation = context.rels.get(attr(child, "r:id") ?? "");
        const href = relation?.external && /^https?:\/\//i.test(relation.target) ? relation.target : "";
        html += href ? `<a href="${escapeHtml(href)}">${inner}</a>` : inner;
        break;
      }
      case "w:sdt":
        html += await inlines(context, find(child, "w:sdtContent") ?? child);
        break;
      case "w:fldSimple":
      case "w:smartTag":
      case "w:ins":
        html += await inlines(context, child);
        break;
      default:
        break;
    }
  }
  return html;
}

function plainText(node: Element): string {
  let text = "";
  walk(node, (element) => {
    if (element.name === "w:t")
      text += children(element)
        .map((t) => String(t.text ?? ""))
        .join("");
  });
  return text;
}

async function paragraph(context: Context, node: Element): Promise<string> {
  let html = await inlines(context, node);
  if (!html.trim()) return "";
  const marker = escapeHtml(context.markers.title);
  if (html.includes(marker)) {
    html = html.replaceAll(marker, escapeHtml(context.title));
    context.hasTitle = true;
  }
  const tag = tagFor(paragraphStyle(node), context.styles);
  const justification = attr(at(node, "w:pPr", "w:jc"), "w:val");
  const align =
    justification === "center"
      ? ' style="text-align:center"'
      : justification === "right" || justification === "end"
        ? ' style="text-align:right"'
        : "";
  const close = tag.split(" ")[0];
  return `<${tag}${align}>${html}</${close}>`;
}

async function table(context: Context, node: Element): Promise<string> {
  const rows: string[] = [];
  for (const row of children(node)) {
    if (row.name !== "w:tr") continue;
    const cells: string[] = [];
    for (const cell of children(row)) {
      if (cell.name !== "w:tc") continue;
      const parts: string[] = [];
      for (const block of children(cell)) {
        if (block.name === "w:p") {
          const inner = await inlines(context, block);
          if (inner.trim()) parts.push(inner);
        } else if (block.name === "w:tbl") parts.push(await table(context, block));
      }
      cells.push(`<td>${parts.join("<br>")}</td>`);
    }
    if (cells.length) rows.push(`<tr>${cells.join("")}</tr>`);
  }
  return rows.length ? `<table>\n${rows.join("\n")}\n</table>` : "";
}

/**
 * The template body around the content placeholder as HTML, read from a Word rendering
 * made with `markers`. `title` replaces the title marker; when `dropLeadTitle` is set, a
 * paragraph holding only the title marker right before the content is left out, because
 * the content starts with its own title heading.
 */
export async function templateBodyHtml(
  zip: Zip,
  styles: StyleMap,
  markers: BodyMarkers,
  options: { title: string; dropLeadTitle: boolean; assetsDir: string },
): Promise<TemplateBody> {
  const document = await parsedPart(zip, "word/document.xml");
  const body = at(document && rootElement(document), "w:body");
  const rels = relationEntries(await parsedPart(zip, "word/_rels/document.xml.rels"));
  const context: Context = {
    zip,
    styles,
    markers,
    title: options.title,
    rels,
    assetsDir: options.assetsDir,
    pictures: 0,
    hasTitle: false,
  };
  const blocks: Element[] = [];
  const collect = (node: Element | undefined) => {
    for (const child of children(node)) {
      if (child.type !== "element") continue;
      if (child.name === "w:sdt") collect(find(child, "w:sdtContent"));
      else if (child.name === "w:p" || child.name === "w:tbl") blocks.push(child);
    }
  };
  collect(body);
  const before: string[] = [];
  const after: string[] = [];
  let target = before;
  for (let index = 0; index < blocks.length; index++) {
    const block = blocks[index]!;
    if (block.name === "w:tbl") {
      const html = await table(context, block);
      if (html) target.push(html);
      continue;
    }
    const text = plainText(block).trim();
    if (text === markers.content) {
      target = after;
      continue;
    }
    if (
      options.dropLeadTitle &&
      text === markers.title &&
      blocks[index + 1] &&
      plainText(blocks[index + 1]!).trim() === markers.content
    )
      continue;
    const html = await paragraph(context, block);
    if (html) target.push(html);
  }
  return { before: before.join("\n"), after: after.join("\n"), hasTitle: context.hasTitle };
}
