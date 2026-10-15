// Runs inside sandbox children only. Turns the Markdown block tree into docx library
// paragraphs and tables written in the template's own styles: headings, lists, quotes, code,
// captions and tables take the style the template defines for them (resolved by name, see
// word/inspect.ts) and fall back to the library's built-in formatting where it defines none.
// List items reference numbering instances the template's numbering part defines for this
// render (word/numbering.ts). Nothing here packs a document: word/apply.ts puts the result
// into the template.
import {
  AlignmentType,
  BorderStyle,
  ExternalHyperlink,
  HeadingLevel,
  ImageRun,
  LevelFormat,
  PageBreak,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
  type IParagraphOptions,
  type ParagraphChild,
} from "docx";
import type { Block, Inline } from "../markdown/parse";
import { fitImage, type DocumentImages } from "./images";
import type { StyleMap } from "./word/inspect";
import { ListParagraph } from "./word/list-paragraph";
import { LIST_LEVELS, type ListIds, type ListNeeds } from "./word/numbering";

export const BULLETS = "bullets";
export const NUMBERS = "numbers";
/** Eneo's list definitions, used by the built-in template. */
export const LIST_CONFIG = [
  {
    reference: BULLETS,
    levels: Array.from({ length: LIST_LEVELS }, (_, level) => ({
      level,
      format: LevelFormat.BULLET,
      text: ["•", "◦", "▪", "•"][level]!,
      alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720 * (level + 1), hanging: 360 } } },
    })),
  },
  {
    reference: NUMBERS,
    levels: Array.from({ length: LIST_LEVELS }, (_, level) => ({
      level,
      format: LevelFormat.DECIMAL,
      text: `%${level + 1}.`,
      alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720 * (level + 1), hanging: 360 } } },
    })),
  },
];
const HEADINGS = [
  HeadingLevel.HEADING_1,
  HeadingLevel.HEADING_2,
  HeadingLevel.HEADING_3,
  HeadingLevel.HEADING_4,
  HeadingLevel.HEADING_5,
  HeadingLevel.HEADING_6,
];

export type RenderOptions = {
  images: DocumentImages;
  /** Usable page area in points, for images. */
  page: { width: number; height: number };
  styles: StyleMap;
  lists: ListIds;
  /** Levels added to every heading: content under a level-1 heading starts at level 2. */
  headingShift?: number;
};

/** Every list block in the order renderBlocks reaches them. */
function* listBlocks(blocks: Block[]): Generator<Extract<Block, { type: "list" }>> {
  for (const block of blocks) {
    if (block.type === "list") {
      yield block;
      for (const item of block.items) yield* listBlocks(item.children);
    } else if (block.type === "quote") yield* listBlocks(block.blocks);
  }
}

/** The list definitions the blocks need, in render order. */
export function listNeeds(blocks: Block[]): ListNeeds {
  const needs: ListNeeds = { bullets: false, numbered: [] };
  for (const list of listBlocks(blocks)) {
    if (list.ordered) needs.numbered.push(list.start);
    else needs.bullets = true;
  }
  return needs;
}

function runs(
  inlines: Inline[],
  styles: StyleMap,
  extra: { italics?: boolean } = {},
): ParagraphChild[] {
  const out: ParagraphChild[] = [];
  for (const run of inlines) {
    const parts = run.text.split("\n");
    parts.forEach((part, index) => {
      const text = new TextRun({
        text: part,
        bold: run.bold,
        italics: run.italic || extra.italics,
        strike: run.strike,
        font: run.code ? "Courier New" : undefined,
        style: run.link ? (styles.hyperlink ?? "Hyperlink") : undefined,
        break: index > 0 ? 1 : undefined,
      });
      out.push(run.link ? new ExternalHyperlink({ children: [text], link: run.link }) : text);
    });
  }
  return out;
}

/** The document title in the template's title style. */
export function titleParagraph(title: string, styles: StyleMap): Paragraph {
  return new Paragraph({
    ...(styles.title ? { style: styles.title } : { heading: HeadingLevel.TITLE }),
    children: [new TextRun(title)],
  });
}

export function renderBlocks(blocks: Block[], options: RenderOptions): (Paragraph | Table)[] {
  const numbered = options.lists.numbered[Symbol.iterator]();
  const nextNumbered = () => {
    const next = numbered.next();
    if (next.done) throw new Error("A numbered list has no numbering instance.");
    return next.value;
  };
  const { images, page, styles } = options;
  const shift = options.headingShift ?? 0;
  const render = (
    blocks: Block[],
    extra: IParagraphOptions & { listLevel?: number } = {},
  ): (Paragraph | Table)[] => {
    const out: (Paragraph | Table)[] = [];
    const level = extra.listLevel ?? 0;
    const { listLevel: _, ...paragraphOptions } = extra;
    for (const block of blocks) {
      switch (block.type) {
        case "image": {
          const image = images.get(block.id)!;
          const size = fitImage(image, page.width - level * 36, page.height - 120);
          out.push(
            new Paragraph({
              alignment: AlignmentType.CENTER,
              keepNext: !!image.caption,
              children: [
                new ImageRun({
                  type: image.type,
                  data: image.bytes,
                  transformation: { width: size.width / 0.75, height: size.height / 0.75 },
                  altText: {
                    name: block.alt || block.id,
                    description: block.alt,
                    title: image.caption ?? block.alt,
                  },
                }),
              ],
            }),
          );
          if (image.caption)
            out.push(
              new Paragraph({
                ...(styles.caption
                  ? { style: styles.caption }
                  : { alignment: AlignmentType.CENTER, spacing: { after: 160 } }),
                keepLines: true,
                children: [
                  new TextRun({
                    text: image.caption,
                    ...(styles.caption ? {} : { italics: true, size: 18 }),
                  }),
                ],
              }),
            );
          break;
        }
        case "heading": {
          const headingLevel = Math.min(block.level + shift, HEADINGS.length);
          const style = styles.heading[headingLevel];
          out.push(
            new Paragraph({
              ...(style ? { style } : { heading: HEADINGS[headingLevel - 1] }),
              children: runs(block.runs, styles),
            }),
          );
          break;
        }
        case "paragraph":
          out.push(
            new Paragraph({
              ...paragraphOptions,
              children: runs(block.runs, styles),
              ...(paragraphOptions.style ? {} : { spacing: { after: 120 } }),
            }),
          );
          break;
        case "list": {
          const listLevel = Math.min(level, LIST_LEVELS - 1);
          const numId = block.ordered ? nextNumbered() : options.lists.bullet!;
          const styleByLevel = block.ordered ? styles.listNumber : styles.listBullet;
          const style = styleByLevel[listLevel] ?? styleByLevel[0] ?? styles.listParagraph;
          for (const item of block.items) {
            out.push(
              new ListParagraph(
                { ...(style ? { style } : {}), children: runs(item.runs, styles) },
                { numId, level: listLevel },
              ),
            );
            out.push(
              ...render(item.children, {
                listLevel: level + 1,
                indent: { left: 720 * (level + 1) },
              }),
            );
          }
          break;
        }
        case "table": {
          const cell = (inlines: Inline[], header: boolean) =>
            new TableCell({
              children: [
                new Paragraph({
                  children: runs(
                    inlines.map((r) => ({ ...r, bold: header || r.bold })),
                    styles,
                  ),
                }),
              ],
            });
          out.push(
            new Table({
              ...(styles.table ? { style: styles.table } : {}),
              width: { size: 100, type: WidthType.PERCENTAGE },
              rows: [
                new TableRow({
                  tableHeader: true,
                  children: block.header.map((h) => cell(h, true)),
                }),
                ...block.rows.map(
                  (row) => new TableRow({ children: row.map((c) => cell(c, false)) }),
                ),
              ],
            }),
          );
          out.push(new Paragraph({ spacing: { after: 120 } }));
          break;
        }
        case "quote":
          out.push(
            ...render(
              block.blocks,
              styles.quote
                ? { style: styles.quote }
                : {
                    indent: { left: 720 },
                    border: {
                      left: { style: BorderStyle.SINGLE, size: 12, color: "999999", space: 8 },
                    },
                  },
            ),
          );
          break;
        case "code":
          for (const line of block.text.split("\n"))
            out.push(
              styles.code
                ? new Paragraph({ style: styles.code, children: [new TextRun(line || " ")] })
                : new Paragraph({
                    children: [new TextRun({ text: line || " ", font: "Courier New", size: 18 })],
                    shading: { fill: "F2F2F2" },
                    spacing: { after: 0 },
                  }),
            );
          out.push(new Paragraph({ spacing: { after: 120 } }));
          break;
        case "hr":
          out.push(
            new Paragraph({
              border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "999999", space: 1 } },
              spacing: { after: 240 },
            }),
          );
          break;
        case "pagebreak":
          out.push(new Paragraph({ children: [new PageBreak()] }));
          break;
      }
    }
    return out;
  };
  return render(blocks);
}
