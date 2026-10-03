import {
  AlignmentType,
  BorderStyle,
  Document,
  ExternalHyperlink,
  HeadingLevel,
  ImageRun,
  LevelFormat,
  Packer,
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
import { parseMarkdown, type Block, type Inline } from "../markdown/parse";
import type { DocumentSpec } from "../ports";

import { fitImage, type DocumentImages } from "./images";
import { pageContentSize } from "./template";

const BULLETS = "bullets";
const NUMBERS = "numbers";
function runs(inlines: Inline[], extra: { italics?: boolean } = {}): ParagraphChild[] {
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
        style: run.link ? "Hyperlink" : undefined,
        break: index > 0 ? 1 : undefined,
      });
      out.push(run.link ? new ExternalHyperlink({ children: [text], link: run.link }) : text);
    });
  }
  return out;
}
function paragraphs(
  blocks: Block[],
  images: DocumentImages,
  page: { width: number; height: number },
  options: IParagraphOptions & { listLevel?: number } = {},
): (Paragraph | Table)[] {
  const out: (Paragraph | Table)[] = [];
  const level = options.listLevel ?? 0;
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
              alignment: AlignmentType.CENTER,
              keepLines: true,
              spacing: { after: 160 },
              children: [new TextRun({ text: image.caption, italics: true, size: 18 })],
            }),
          );
        break;
      }
      case "heading":
        out.push(
          new Paragraph({
            heading: [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][
              block.level - 1
            ],
            children: runs(block.runs),
          }),
        );
        break;
      case "paragraph":
        out.push(
          new Paragraph({ ...options, children: runs(block.runs), spacing: { after: 120 } }),
        );
        break;
      case "list":
        block.items.forEach((item, index) => {
          out.push(
            new Paragraph({
              children: runs(item.runs),
              numbering: {
                reference: block.ordered ? NUMBERS : BULLETS,
                level: Math.min(level, 3),
                ...(block.ordered && index === 0 && block.start !== 1
                  ? { instance: block.start }
                  : {}),
              },
            }),
          );
          out.push(
            ...paragraphs(item.children, images, page, {
              listLevel: level + 1,
              indent: { left: 720 * (level + 1) },
            }),
          );
        });
        break;
      case "table": {
        const cell = (inlines: Inline[], header: boolean) =>
          new TableCell({
            children: [
              new Paragraph({
                children: runs(inlines.map((r) => ({ ...r, bold: header || r.bold }))),
              }),
            ],
          });
        out.push(
          new Table({
            width: { size: 100, type: WidthType.PERCENTAGE },
            rows: [
              new TableRow({ tableHeader: true, children: block.header.map((h) => cell(h, true)) }),
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
          ...paragraphs(block.blocks, images, page, {
            indent: { left: 720 },
            border: { left: { style: BorderStyle.SINGLE, size: 12, color: "999999", space: 8 } },
          }),
        );
        break;
      case "code":
        for (const line of block.text.split("\n"))
          out.push(
            new Paragraph({
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
}
export async function renderDocx(
  document: Extract<DocumentSpec, { kind: "markdown" }>,
  options: { organisationName?: string; images?: DocumentImages; template?: Buffer } = {},
): Promise<Buffer> {
  const blocks = parseMarkdown(document.content);
  const body: (Paragraph | Table)[] = [];
  const startsWithTitle = blocks[0]?.type === "heading" && blocks[0].level === 1;
  if (!startsWithTitle)
    body.push(
      new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun(document.title)] }),
    );
  const page =
    options.template && document.images?.length
      ? await pageContentSize(options.template)
      : { width: 451, height: 650 };
  body.push(...paragraphs(blocks, options.images ?? new Map(), page));
  const doc = new Document({
    title: document.title,
    creator: options.organisationName ?? "Eneo",
    description: "",
    numbering: {
      config: [
        {
          reference: BULLETS,
          levels: [0, 1, 2, 3].map((level) => ({
            level,
            format: LevelFormat.BULLET,
            text: ["•", "◦", "▪", "•"][level]!,
            alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720 * (level + 1), hanging: 360 } } },
          })),
        },
        {
          reference: NUMBERS,
          levels: [0, 1, 2, 3].map((level) => ({
            level,
            format: LevelFormat.DECIMAL,
            text: `%${level + 1}.`,
            alignment: AlignmentType.LEFT,
            style: { paragraph: { indent: { left: 720 * (level + 1), hanging: 360 } } },
          })),
        },
      ],
    },
    styles: {
      default: { document: { run: { font: "Calibri", size: 22 } } },
    },
    sections: [{ children: body }],
  });
  return Buffer.from(await Packer.toBuffer(doc));
}
