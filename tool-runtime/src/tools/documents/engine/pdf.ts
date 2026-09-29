import PDFDocument from "pdfkit";
import { parseMarkdown, plainText, type Block, type Inline } from "../markdown/parse";
import type { DocumentSpec } from "../ports";
import { RenderError, type Rendered } from "./render";

// The image ships DejaVu (fonts-dejavu-core); the child's environment is allowlisted, so the
// paths are constants rather than settings.
const FONT_DIR = "/usr/share/fonts/truetype/dejavu";
// fonts-dejavu-core has no oblique faces; italic text is rendered upright.
const FONTS = {
  body: `${FONT_DIR}/DejaVuSans.ttf`,
  bold: `${FONT_DIR}/DejaVuSans-Bold.ttf`,
  mono: `${FONT_DIR}/DejaVuSansMono.ttf`,
};
const MARGIN = 56;
const BODY = 10.5;
const HEADINGS = [20, 15, 12.5];
function fontFor(run: Inline): keyof typeof FONTS {
  if (run.code) return "mono";
  if (run.bold) return "bold";
  return "body";
}
async function fontsAvailable(): Promise<void> {
  for (const path of Object.values(FONTS))
    if (!(await Bun.file(path).exists()))
      throw new RenderError("PDF fonts are missing on this runtime; install fonts-dejavu-core.");
}
export async function renderPdf(
  document: Extract<DocumentSpec, { kind: "markdown" }>,
  options: { organisationName?: string } = {},
): Promise<Rendered> {
  await fontsAvailable();
  const blocks = parseMarkdown(document.content);
  const pdf = new PDFDocument({
    size: "A4",
    margins: { top: MARGIN, bottom: MARGIN + 16, left: MARGIN, right: MARGIN },
    bufferPages: true,
    info: { Title: document.title, Author: options.organisationName ?? "Eneo" },
    lang: document.language,
  });
  for (const [name, path] of Object.entries(FONTS)) pdf.registerFont(name, path);
  const chunks: Buffer[] = [];
  pdf.on("data", (chunk: Buffer) => chunks.push(chunk));
  const finished = new Promise<void>((resolve, reject) => {
    pdf.on("end", () => resolve());
    pdf.on("error", reject);
  });
  const width = () => pdf.page.width - pdf.page.margins.left - pdf.page.margins.right;
  const writeRuns = (inlines: Inline[], size: number, extra: PDFKit.Mixins.TextOptions = {}) => {
    const pieces = inlines.filter((r) => r.text.length);
    if (!pieces.length) return pdf.moveDown(0.3);
    pieces.forEach((run, index) => {
      pdf.font(fontFor(run)).fontSize(size);
      const last = index === pieces.length - 1;
      pdf.text(run.text, {
        ...extra,
        continued: !last,
        link: run.link,
        underline: !!run.link,
        strike: run.strike,
      });
    });
    return pdf;
  };
  const write = (list: Block[], indent = 0) => {
    for (const block of list) {
      switch (block.type) {
        case "heading":
          pdf.moveDown(block.level === 1 ? 0.6 : 0.4);
          writeRuns(
            block.runs.map((r) => ({ ...r, bold: true })),
            HEADINGS[block.level - 1]!,
            { indent },
          );
          pdf.moveDown(0.3);
          break;
        case "paragraph":
          writeRuns(block.runs, BODY, { indent, align: "left" });
          pdf.moveDown(0.5);
          break;
        case "list":
          block.items.forEach((item, index) => {
            const marker = block.ordered ? `${block.start + index}.` : "•";
            const x = pdf.page.margins.left + indent;
            const y = pdf.y;
            pdf.font("body").fontSize(BODY).text(marker, x, y, { width: 18, lineBreak: false });
            pdf.x = x + 18;
            pdf.y = y;
            const saved = pdf.page.margins.left;
            pdf.page.margins.left = x + 18;
            writeRuns(item.runs, BODY, { width: width() });
            pdf.moveDown(0.2);
            write(item.children, 0);
            pdf.page.margins.left = saved;
            pdf.x = saved;
          });
          pdf.moveDown(0.3);
          break;
        case "table": {
          const columns = block.header.length || 1;
          const columnWidth = (width() - indent) / columns;
          const drawRow = (cells: Inline[][], header: boolean) => {
            const x0 = pdf.page.margins.left + indent;
            let height = 0;
            cells.forEach((cell) => {
              pdf.font(header ? "bold" : "body").fontSize(BODY - 1);
              height = Math.max(
                height,
                pdf.heightOfString(plainText(cell) || " ", { width: columnWidth - 6 }),
              );
            });
            if (pdf.y + height + 6 > pdf.page.height - pdf.page.margins.bottom) pdf.addPage();
            const y = pdf.y;
            cells.forEach((cell, index) => {
              pdf.font(header ? "bold" : "body").fontSize(BODY - 1);
              pdf.text(plainText(cell), x0 + index * columnWidth + 3, y + 3, {
                width: columnWidth - 6,
              });
            });
            pdf
              .moveTo(x0, y + height + 6)
              .lineTo(x0 + columnWidth * columns, y + height + 6)
              .lineWidth(header ? 1 : 0.3)
              .strokeColor("#888888")
              .stroke();
            pdf.x = pdf.page.margins.left;
            pdf.y = y + height + 8;
          };
          drawRow(block.header, true);
          for (const row of block.rows) drawRow(row, false);
          pdf.moveDown(0.5);
          break;
        }
        case "quote": {
          const saved = pdf.page.margins.left;
          pdf.page.margins.left = saved + 18;
          pdf.x = pdf.page.margins.left;
          write(
            block.blocks.map((b) =>
              b.type === "paragraph"
                ? { ...b, runs: b.runs.map((r) => ({ ...r, italic: true })) }
                : b,
            ),
            0,
          );
          pdf.page.margins.left = saved;
          pdf.x = saved;
          break;
        }
        case "code":
          pdf
            .font("mono")
            .fontSize(BODY - 1.5)
            .text(block.text, { indent });
          pdf.moveDown(0.6);
          break;
        case "hr":
          pdf.moveDown(0.2);
          pdf
            .moveTo(pdf.page.margins.left, pdf.y)
            .lineTo(pdf.page.width - pdf.page.margins.right, pdf.y)
            .lineWidth(0.5)
            .strokeColor("#999999")
            .stroke();
          pdf.moveDown(0.6);
          break;
        case "pagebreak":
          pdf.addPage();
          break;
      }
    }
  };
  const startsWithTitle = blocks[0]?.type === "heading" && blocks[0].level === 1;
  if (!startsWithTitle) {
    pdf.font("bold").fontSize(HEADINGS[0]!).text(document.title);
    pdf.moveDown(0.5);
  }
  write(blocks);
  const range = pdf.bufferedPageRange();
  for (let index = 0; index < range.count; index++) {
    pdf.switchToPage(index);
    const footer = `${options.organisationName ? `${options.organisationName} · ` : ""}${document.language === "en" ? "Page" : "Sida"} ${index + 1} ${document.language === "en" ? "of" : "av"} ${range.count}`;
    const bottom = pdf.page.margins.bottom;
    pdf.page.margins.bottom = 0;
    pdf
      .font("body")
      .fontSize(8)
      .fillColor("#666666")
      .text(footer, MARGIN, pdf.page.height - MARGIN + 4, {
        width: pdf.page.width - 2 * MARGIN,
        align: "center",
        lineBreak: false,
      });
    pdf.page.margins.bottom = bottom;
  }
  pdf.end();
  await finished;
  return { buffer: Buffer.concat(chunks), pages: range.count };
}
