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
  // An image answers to its ID and to its handle, whichever the content places it by.
  const keys = declared.map((image) => [image.id, image.handle].filter((key) => !!key) as string[]);
  const all = keys.flat();
  if (declared.length > 8 || new Set(all).size !== all.length || keys.some((own) => !own.length))
    throw new RenderError("Use at most eight images with unique IDs.");
  const used = new Map<string, string | undefined>();
  const visit = (blocks: Block[]) => {
    for (const block of blocks) {
      if (block.type === "image") used.set(block.id, used.get(block.id) ?? block.caption);
      if (block.type === "quote") visit(block.blocks);
      if (block.type === "list") for (const item of block.items) visit(item.children);
    }
  };
  visit(parseMarkdown(document.content));
  // An image declared for a line the document already has needs no ID, and that line may
  // since have been edited away; an ID is declared to be placed.
  if (
    [...used.keys()].some((id) => !all.includes(id)) ||
    declared.some((image, index) => image.id && !keys[index]!.some((key) => used.has(key)))
  )
    throw new RenderError(
      "Every image must be declared in images and placed on a line of its own: ![alt text](image:ID) for a declared ID, or the document's existing ![alt text](eneo-file:…) line with that same eneo-file value passed as the image's url. No undeclared images.",
    );
  const images: DocumentImages = new Map();
  let total = 0;
  for (const [index, image] of declared.entries()) {
    if (!image.path) throw new RenderError("An image was not downloaded.");
    const bytes = await readFile(image.path);
    total += bytes.length;
    if (bytes.length > 10 * 1024 * 1024 || total > 32 * 1024 * 1024)
      throw new RenderError("Document images exceed the size limit.");
    const bitmap = {
      bytes,
      ...imageDimensions(bytes),
      // A Markdown document carries the caption in its image line.
      caption: image.caption ?? keys[index]!.map((key) => used.get(key)).find((text) => !!text),
      widthPercent: image.widthPercent ?? 100,
    };
    for (const key of keys[index]!) images.set(key, bitmap);
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
