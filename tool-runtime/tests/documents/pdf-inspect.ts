// What the PDF tests look at: WeasyPrint writes object streams, so the catalog, the
// structure tree and the font dictionaries are not visible in the raw bytes.
import { PDFDict, PDFDocument, PDFName, PDFRawStream, PDFString, PDFHexString } from "pdf-lib";
import { inflateSync } from "node:zlib";

export type PdfFacts = {
  lang?: string;
  title?: string;
  marked: boolean;
  structured: boolean;
  fonts: string[];
  pageSize: [number, number];
  pages: number;
  xmp: string;
};

export async function inspectPdf(buffer: Buffer): Promise<PdfFacts> {
  const pdf = await PDFDocument.load(buffer, { updateMetadata: false });
  const catalog = pdf.catalog;
  const text = (value: unknown) =>
    value instanceof PDFString || value instanceof PDFHexString ? value.decodeText() : undefined;
  const markInfo = catalog.lookup(PDFName.of("MarkInfo"));
  const fonts = new Set<string>();
  for (const page of pdf.getPages()) {
    const resources = page.node.Resources();
    const dict = resources?.lookup(PDFName.of("Font"));
    if (!(dict instanceof PDFDict)) continue;
    for (const [, ref] of dict.entries()) {
      const font = pdf.context.lookup(ref);
      const base = font instanceof PDFDict ? font.get(PDFName.of("BaseFont")) : undefined;
      if (base) fonts.add(base.toString().replace(/^\//, ""));
    }
  }
  let xmp = "";
  const metadata = catalog.lookup(PDFName.of("Metadata"));
  if (metadata instanceof PDFRawStream) {
    const raw = Buffer.from(metadata.contents);
    xmp = (metadata.dict.get(PDFName.of("Filter")) ? inflateSync(raw) : raw).toString("utf8");
  }
  const first = pdf.getPage(0);
  return {
    lang: text(catalog.get(PDFName.of("Lang"))),
    title: pdf.getTitle(),
    marked:
      markInfo instanceof PDFDict && markInfo.get(PDFName.of("Marked"))?.toString() === "true",
    structured: catalog.has(PDFName.of("StructTreeRoot")),
    fonts: [...fonts].sort(),
    pageSize: [first.getWidth(), first.getHeight()],
    pages: pdf.getPageCount(),
    xmp,
  };
}
