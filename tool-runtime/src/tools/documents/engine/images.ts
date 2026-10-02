// Runs only in the render sandbox. Images are declared local inputs, never fetched here.
import { readFile } from "node:fs/promises";
import { RenderError } from "./render";
import { parseMarkdown, type Block } from "../markdown/parse";
import type { DocumentSpec } from "../ports";

export type DocumentBitmap = {
  bytes: Buffer;
  type: "png" | "jpg";
  width: number;
  height: number;
  caption?: string;
  widthPercent: number;
};
export type DocumentImages = Map<string, DocumentBitmap>;

/** Read dimensions before an image decoder can allocate an unbounded raster. */
export function imageDimensions(bytes: Buffer): Pick<DocumentBitmap, "type" | "width" | "height"> {
  let width = 0,
    height = 0;
  let type: "png" | "jpg" = "png";
  if (
    bytes.length >= 33 &&
    bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) &&
    bytes.readUInt32BE(8) === 13 &&
    bytes.toString("ascii", 12, 16) === "IHDR"
  ) {
    width = bytes.readUInt32BE(16);
    height = bytes.readUInt32BE(20);
  } else if (bytes.length >= 4 && bytes[0] === 255 && bytes[1] === 216) {
    type = "jpg";
    let offset = 2;
    while (offset + 4 <= bytes.length) {
      if (bytes[offset++] !== 255) break;
      while (bytes[offset] === 255) offset++;
      const marker = bytes[offset++];
      if (marker === 0xda || marker === 0xd9) break;
      if (marker === 0x01 || (marker! >= 0xd0 && marker! <= 0xd7)) continue;
      if (offset + 2 > bytes.length) break;
      const length = bytes.readUInt16BE(offset);
      if (length < 2 || offset + length > bytes.length) break;
      if ([0xc0, 0xc1, 0xc2].includes(marker!) && length >= 8) {
        height = bytes.readUInt16BE(offset + 3);
        width = bytes.readUInt16BE(offset + 5);
        break;
      }
      offset += length;
    }
  }
  if (!width || !height || width > 12000 || height > 12000 || width * height > 16_000_000)
    throw new RenderError(
      "Use a valid PNG or JPEG image of at most 16 megapixels and 12000 pixels per side.",
    );
  return { type, width, height };
}

export async function loadDocumentImages(
  document: Extract<DocumentSpec, { kind: "markdown" }>,
): Promise<DocumentImages> {
  const declared = document.images ?? [];
  if (declared.length > 8 || new Set(declared.map((i) => i.id)).size !== declared.length)
    throw new RenderError("Use at most eight images with unique IDs.");
  const used = new Set<string>();
  const visit = (blocks: Block[]) => {
    for (const block of blocks) {
      if (block.type === "image") used.add(block.id);
      if (block.type === "quote") visit(block.blocks);
      if (block.type === "list") for (const item of block.items) visit(item.children);
    }
  };
  visit(parseMarkdown(document.content));
  if (used.size !== declared.length || declared.some((i) => !used.has(i.id)))
    throw new RenderError(
      "Every image must have a matching standalone ![alt text](image:ID) in the document, with no undeclared image IDs.",
    );
  const images: DocumentImages = new Map();
  let total = 0;
  for (const image of declared) {
    if (!image.path) throw new RenderError("An image was not downloaded.");
    const bytes = await readFile(image.path);
    total += bytes.length;
    if (bytes.length > 10 * 1024 * 1024 || total > 32 * 1024 * 1024)
      throw new RenderError("Document images exceed the size limit.");
    images.set(image.id, {
      bytes,
      ...imageDimensions(bytes),
      caption: image.caption,
      widthPercent: image.widthPercent ?? 100,
    });
  }
  return images;
}

/** Fit without stretching, and never enlarge beyond the image's native 96-dpi size. */
export function fitImage(image: DocumentBitmap, maxWidth: number, maxHeight: number) {
  const scale = Math.min(
    0.75,
    (maxWidth * image.widthPercent) / 100 / image.width,
    maxHeight / image.height,
  );
  return { width: image.width * scale, height: image.height * scale };
}
