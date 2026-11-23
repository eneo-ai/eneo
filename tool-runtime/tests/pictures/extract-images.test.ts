import { describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { inflateSync } from "node:zlib";
import JSZip from "jszip";
import { Resvg } from "@resvg/resvg-js";
import { ToolError } from "../../src/errors";
import { jobPaths, runIsolated } from "../../src/sandbox";
import { pdfAvailable } from "../../src/tools/documents/engine/pdf";
import { imageDimensions } from "../../src/tools/documents/engine/images";
import { executeExtractImages } from "../../src/tools/pictures/execute";
import type { ExtractImagesJob, ExtractImagesResult } from "../../src/tools/pictures/ports";
import { PICTURES_PER_CALL, pictureTools } from "../../src/tools/pictures/tool";
import { RichResult } from "../../src/tools/types";

// The extraction runs in the Python sidecar the image installs; without it these are skipped.
const SIDECAR = await pdfAvailable();
const origin = "http://backend:8000";
const url = `${origin}/api/v1/files/11111111-1111-4111-8111-111111111111/original/download/?token=current`;
const context = { tenantId: "tenant", userId: "user", fileOrigin: origin };
const RED = [200, 30, 30] as const;
const BLUE = [10, 90, 160] as const;

type Placement = [name: string, x: number, y: number, width: number, height: number];
type Images = Record<string, { pixels: number; colour: readonly number[] }>;

/**
 * A PDF whose A4 pages place named square images at (x, y) in the given size, in points.
 * Pages share one image object per name, as a document that repeats a logo does.
 */
function pdf(pages: Placement[][], images: Images): Buffer {
  const objects = new Map<number, Buffer>();
  const ids = new Map(Object.keys(images).map((name, index) => [name, 10 + index]));
  const stream = (dictionary: string, data: Buffer) =>
    Buffer.concat([
      Buffer.from(`<< ${dictionary} /Length ${data.length} >>\nstream\n`),
      data,
      Buffer.from("\nendstream"),
    ]);
  for (const [name, { pixels, colour }] of Object.entries(images))
    objects.set(
      ids.get(name)!,
      stream(
        `/Type /XObject /Subtype /Image /Width ${pixels} /Height ${pixels} /ColorSpace /DeviceRGB /BitsPerComponent 8`,
        Buffer.alloc(pixels * pixels * 3, Buffer.from(colour)),
      ),
    );
  const xobjects = [...ids].map(([name, id]) => `/${name} ${id} 0 R`).join(" ");
  const pageIds = pages.map((placements, index) => {
    const pageId = 100 + 2 * index;
    objects.set(
      pageId + 1,
      stream(
        "",
        Buffer.from(
          placements
            .map(
              ([name, x, y, width, height]) =>
                `q ${width} 0 0 ${height} ${x} ${y} cm /${name} Do Q`,
            )
            .join("\n"),
        ),
      ),
    );
    objects.set(
      pageId,
      Buffer.from(
        `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /XObject << ${xobjects} >> >> /Contents ${pageId + 1} 0 R >>`,
      ),
    );
    return pageId;
  });
  objects.set(1, Buffer.from("<< /Type /Catalog /Pages 2 0 R >>"));
  objects.set(
    2,
    Buffer.from(
      `<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(" ")}] /Count ${pages.length} >>`,
    ),
  );
  const parts: Buffer[] = [Buffer.from("%PDF-1.4\n")];
  const offsets = new Map<number, number>();
  let length = parts[0]!.length;
  const push = (part: Buffer) => {
    parts.push(part);
    length += part.length;
  };
  for (const id of [...objects.keys()].sort((a, b) => a - b)) {
    offsets.set(id, length);
    push(
      Buffer.concat([Buffer.from(`${id} 0 obj\n`), objects.get(id)!, Buffer.from("\nendobj\n")]),
    );
  }
  const size = Math.max(...objects.keys()) + 1;
  const start = length;
  push(Buffer.from(`xref\n0 ${size}\n`));
  for (let id = 0; id < size; id++)
    push(
      Buffer.from(
        offsets.has(id)
          ? `${String(offsets.get(id)).padStart(10, "0")} 00000 n \n`
          : "0000000000 65535 f \n",
      ),
    );
  push(Buffer.from(`trailer\n<< /Size ${size} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`));
  return Buffer.concat(parts);
}

function png(width: number, height: number): Buffer {
  return Buffer.from(
    new Resvg(
      `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="rgb(${RED.join(",")})"/></svg>`,
    )
      .render()
      .asPng(),
  );
}

async function office(directory: string, media: Record<string, Buffer>): Promise<Buffer> {
  const zip = new JSZip();
  zip.file("[Content_Types].xml", "<Types/>");
  for (const [name, bytes] of Object.entries(media)) zip.file(`${directory}${name}`, bytes);
  return zip.generateAsync({ type: "nodebuffer" });
}

/** The first pixel of a PNG: whatever filter its first row uses, that pixel is stored as is. */
function firstPixel(bytes: Buffer): number[] {
  const data: Buffer[] = [];
  for (let offset = 8; offset < bytes.length;) {
    const size = bytes.readUInt32BE(offset);
    if (bytes.toString("ascii", offset + 4, offset + 8) === "IDAT")
      data.push(bytes.subarray(offset + 8, offset + 8 + size));
    offset += 12 + size;
  }
  return [...inflateSync(Buffer.concat(data)).subarray(1, 4)];
}

function tool(bytes: Buffer, extract = executeExtractImages) {
  return pictureTools(extract, {
    allowedFileOrigins: [],
    maxBytes: 20e6,
    timeoutMs: 1000,
    download: async () => ({ bytes, contentType: "application/octet-stream" }) as never,
  })[0]!;
}

const logo: Placement = ["Logo", 40, 760, 60, 60];
const report = pdf([[logo], [logo, ["Figure", 100, 300, 240, 120]]], {
  Logo: { pixels: 120, colour: BLUE },
  Figure: { pixels: 240, colour: RED },
});

describe.skipIf(!SIDECAR)("extract_images", () => {
  test("a PDF's pictures come back as images, a repeated one once", async () => {
    const result = (await tool(report).execute(
      { file: { url, filename: "Rapport.pdf" } },
      context,
    )) as RichResult;

    expect(result.structured).toMatchObject({
      file: "Rapport.pdf",
      total: 2,
      images: [
        { image: 1, number_in_file: 1, page: 1, width: 120, height: 120 },
        { image: 2, number_in_file: 2, page: 2, width: 240, height: 120 },
      ],
    });
    expect(result.structured.next_offset).toBeUndefined();
    expect(result.files).toEqual([]);
    expect(result.images.map((image) => image.mimeType)).toEqual(["image/png", "image/png"]);
    // Each is the region the page shows the picture in: the logo, then the 2:1 figure.
    const [first, second] = result.images.map((image) => Buffer.from(image.data, "base64"));
    expect(firstPixel(first!)).toEqual([...BLUE]);
    expect(firstPixel(second!)).toEqual([...RED]);
    expect(imageDimensions(second!)).toMatchObject({
      type: "png",
      width: 240,
      height: 120,
    });
  });

  test("page limits a PDF to that page and still skips an earlier repeat", async () => {
    const result = (await tool(report).execute(
      { file: { url, filename: "Rapport.pdf" }, page: 2 },
      context,
    )) as RichResult;

    expect(result.structured).toMatchObject({
      page: 2,
      total: 1,
      images: [{ image: 1, page: 2 }],
    });
    expect(firstPixel(Buffer.from(result.images[0]!.data, "base64"))).toEqual([...RED]);
  });

  test("a call returns a bounded number of pictures and names the next offset", async () => {
    const names = Array.from({ length: PICTURES_PER_CALL + 2 }, (_, index) => `F${index}`);
    const many = pdf(
      names.map((name) => [[name, 100, 300, 150, 150]]),
      Object.fromEntries(
        names.map((name, index) => [name, { pixels: 150, colour: [index * 30, 30, 30] }]),
      ),
    );

    const first = (await tool(many).execute(
      { file: { url, filename: "Bilaga.pdf" } },
      context,
    )) as RichResult;
    const rest = (await tool(many).execute(
      {
        file: { url, filename: "Bilaga.pdf" },
        offset: first.structured.next_offset,
      },
      context,
    )) as RichResult;

    expect(first.images).toHaveLength(PICTURES_PER_CALL);
    expect(first.structured).toMatchObject({
      total: names.length,
      next_offset: PICTURES_PER_CALL,
    });
    expect(rest.images).toHaveLength(2);
    expect(rest.structured.next_offset).toBeUndefined();
    expect(rest.structured.images).toMatchObject([
      {
        image: 1,
        number_in_file: PICTURES_PER_CALL + 1,
        page: PICTURES_PER_CALL + 1,
      },
      {
        image: 2,
        number_in_file: PICTURES_PER_CALL + 2,
        page: PICTURES_PER_CALL + 2,
      },
    ]);
  });

  test("icons and thin decorations are not pictures, and the result says none were found", async () => {
    const decorated = pdf(
      [
        [
          ["Icon", 100, 300, 80, 80],
          ["Rule", 100, 500, 300, 10],
        ],
      ],
      {
        Icon: { pixels: 32, colour: BLUE },
        Rule: { pixels: 200, colour: BLUE },
      },
    );

    const result = await tool(decorated).execute({ file: { url, filename: "Brev.pdf" } }, context);

    expect(result).not.toBeInstanceOf(RichResult);
    expect(result).toMatchObject({ file: "Brev.pdf", total: 0 });
    expect((result as { note: string }).note).toContain("vector graphics cannot be extracted");
  });

  test("an offset past the last picture returns no image", async () => {
    const result = await tool(report).execute(
      { file: { url, filename: "Rapport.pdf" }, offset: 5 },
      context,
    );

    expect(result).not.toBeInstanceOf(RichResult);
    expect(result).toMatchObject({
      total: 2,
      note: "Offset 5 is past the last picture.",
    });
  });

  test("a Word file's embedded pictures come out in media order, small ones left out", async () => {
    const docx = await office("word/media/", {
      "image10.png": png(400, 300),
      "image2.png": png(40, 40),
      "image1.png": png(300, 200),
      "image3.emf": Buffer.from("not a raster image"),
    });

    const result = (await tool(docx).execute(
      { file: { url, filename: "Riktlinje.docx" }, page: 3 },
      context,
    )) as RichResult;

    // page applies to a PDF only.
    expect(result.structured.page).toBeUndefined();
    expect(result.structured).toMatchObject({
      total: 2,
      images: [
        { image: 1, width: 300, height: 200 },
        { image: 2, width: 400, height: 300 },
      ],
    });
    expect(firstPixel(Buffer.from(result.images[0]!.data, "base64"))).toEqual([...RED]);
  });

  test("a PowerPoint file's pictures are read from its own media directory", async () => {
    const pptx = await office("ppt/media/", { "image1.png": png(640, 360) });

    const result = (await tool(pptx).execute(
      { file: { url, filename: "Presentation.pptx" } },
      context,
    )) as RichResult;

    expect(result.structured).toMatchObject({
      total: 1,
      images: [{ width: 640, height: 360 }],
    });
  });

  test("a file that cannot be parsed fails without the parser's own message", async () => {
    const failure = await tool(Buffer.from("not a pdf at all"))
      .execute({ file: { url, filename: "Trasig.pdf" } }, context)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ToolError);
    expect((failure as ToolError).code).toBe("EXTRACTION_FAILED");
    expect((failure as ToolError).message).not.toContain("PDFium");
  });

  test("the job's directory is removed whether the call succeeds or fails", async () => {
    const seen: string[] = [];
    const recording = async (job: ExtractImagesJob): Promise<ExtractImagesResult> => {
      seen.push(job.directory);
      return executeExtractImages(job);
    };

    await tool(report, recording).execute({ file: { url, filename: "Rapport.pdf" } }, context);
    await tool(Buffer.from("broken"), recording)
      .execute({ file: { url, filename: "Trasig.pdf" } }, context)
      .catch(() => undefined);

    expect(seen).toHaveLength(2);
    for (const directory of seen)
      expect(await Bun.file(join(directory, "source")).exists()).toBe(false);
  });

  test("a sandbox child may write only into the directory made for the call", async () => {
    const directory = await mkdtemp(join(tmpdir(), "eneo-pictures-test-"));
    try {
      await writeFile(join(directory, "source"), report);
      await mkdir(join(directory, "out"));
      const job: ExtractImagesJob = {
        kind: "extract_images",
        directory,
        fileKind: "pdf",
        offset: 0,
        limit: PICTURES_PER_CALL,
        maxPages: 200,
      };

      expect(jobPaths(job)).toEqual({ write: [directory] });
      const result = (await runIsolated({ job }, 25_000)) as ExtractImagesResult;

      expect(result.total).toBe(2);
      expect((await readdir(join(directory, "out"))).sort()).toEqual(
        result.pictures.map((picture) => picture.file).sort(),
      );
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });
});

describe("extract_images input", () => {
  test("only PDF, Word and PowerPoint files are accepted", async () => {
    const failure = await tool(Buffer.from("a,b"))
      .execute({ file: { url, filename: "Budget.csv" } }, context)
      .catch((error: unknown) => error);

    expect(String(failure)).toContain("Only .pdf and .docx and .pptx files are supported");
  });
});
