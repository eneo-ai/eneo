import { describe, expect, test } from "bun:test";
import JSZip from "jszip";
import { Resvg } from "@resvg/resvg-js";
import { documentConfigSchema } from "../../src/tools/documents/config";
import { executeRender } from "../../src/tools/documents/execute";
import { documentTools, fileRenderer } from "../../src/tools/documents/tool";
import { imageDimensions } from "../../src/tools/documents/engine/images";
import { pageContentSize } from "../../src/tools/documents/engine/template";
import { RichResult } from "../../src/tools/types";
import { chartTools } from "../../src/tools/charts/tool";
import { executeChart } from "../../src/tools/charts/execute";
import { chartConfigSchema } from "../../src/tools/charts/config";
import { runIsolated } from "../../src/sandbox";
import type { downloadFile } from "../../src/tools/tabular/download";

const origin = "http://backend:8000";
const url = `${origin}/api/v1/files/11111111-1111-4111-8111-111111111111/original/download/?token=current`;
const context = { tenantId: "tenant", userId: "user", fileOrigin: origin, showsViews: true };
const chart = chartTools(chartConfigSchema.parse({}), executeChart, {
  allowedFileOrigins: [],
  maxBytes: 10e6,
  timeoutMs: 1000,
})[0]!;
const chartInput = {
  type: "bar",
  title: "Budget och utfall",
  labels: ["Januari", "Februari"],
  series: [
    { name: "Budget", values: [120, 135] },
    { name: "Utfall", values: [130, 140] },
  ],
  format: "png",
  display: "none",
};
const result = (await chart.execute(chartInput, context)) as RichResult;
const png = Buffer.from(result.images[0]!.data, "base64");
const input = {
  title: "Ekonomirapport",
  format: "docx",
  content:
    "# Ekonomirapport\n\nJanuari–februari.\n\n![Budget och utfall](image:budget)\n\nSlutsats efter diagrammet.",
  images: [
    {
      id: "budget",
      url,
      filename: "generated_image.png",
      caption: "Figur 1. Budget och utfall i miljoner kronor.",
    },
  ],
};
function tool(bytes = png, download?: typeof downloadFile) {
  return documentTools(documentConfigSchema.parse({}), fileRenderer(executeRender), {
    allowedFileOrigins: [],
    maxBytes: 20e6,
    timeoutMs: 1000,
    download:
      download ??
      ((async () => ({
        bytes,
        contentType: "image/png",
        name: "chart.png",
      })) as unknown as typeof downloadFile),
  })[0]!;
}
const bytesOf = (value: RichResult) => Buffer.from(value.files[0]!.blob, "base64");

const jpeg = Buffer.from(
  "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAKABQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwCnRRRX0p5AUUUUAf/Z",
  "base64",
);

describe("document chart images", () => {
  test("JPEG images embed in both export formats", async () => {
    expect(imageDimensions(jpeg)).toEqual({ type: "jpg", width: 20, height: 10 });
    for (const format of ["docx", "pdf"]) {
      const output = (await tool(jpeg).execute(
        { ...input, format, images: [{ ...input.images[0], filename: "external-chart.jpg" }] },
        context,
      )) as RichResult;
      if (format === "docx") {
        const zip = await JSZip.loadAsync(bytesOf(output));
        expect(Object.keys(zip.files).some((name) => name.endsWith(".jpg"))).toBe(true);
      } else expect(bytesOf(output).toString("latin1")).toContain("/DCTDecode");
    }
  });

  test("tall figures shrink to fit and move together with their caption", async () => {
    const tall = Buffer.from(
      new Resvg(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="2000"><rect width="100" height="2000" fill="steelblue"/></svg>',
      )
        .render()
        .asPng(),
    );
    const output = (await tool(tall).execute(
      {
        ...input,
        format: "pdf",
        content: "# Rapport\n\n" + "Inledning.\n\n".repeat(24) + "![Tall figure](image:budget)",
      },
      context,
    )) as RichResult;
    expect(output.structured.pages).toBe(2);
    await Bun.write("/tmp/eneo-tall-image.pdf", bytesOf(output));
    const word = (await tool(tall).execute(input, context)) as RichResult;
    const zip = await JSZip.loadAsync(bytesOf(word));
    const xml = await zip.file("word/document.xml")!.async("string");
    const dimensions = /<wp:extent cx="(\d+)" cy="(\d+)"/.exec(xml)!;
    const width = Number(dimensions[1]) / 12700;
    const height = Number(dimensions[2]) / 12700;
    expect(height).toBeLessThanOrEqual(531);
    expect(height / width).toBeCloseTo(20, 2);
  });

  test("a chart export becomes an embedded Word image, caption and alt text", async () => {
    expect(result.structured.shown_to_user).toBe(false);
    expect(result.images).toHaveLength(1);
    const output = (await tool().execute(input, context)) as RichResult;
    const zip = await JSZip.loadAsync(bytesOf(output));
    const media = Object.keys(zip.files).filter((name) => /word\/media\/.*\.png$/.test(name));
    expect(media).toHaveLength(1);
    expect(await zip.file(media[0]!)!.async("nodebuffer")).toEqual(png);
    const xml = await zip.file("word/document.xml")!.async("string");
    expect(xml).toContain("Figur 1. Budget och utfall");
    expect(xml).toContain("Slutsats efter diagrammet");
    expect(xml).toContain('descr="Budget och utfall"');
    expect(xml).not.toContain("token=");
    expect(xml).not.toContain("image:budget");
    const dimensions = /<wp:extent cx="(\d+)" cy="(\d+)"/.exec(xml)!;
    expect(Number(dimensions[1]) / 12700).toBeLessThanOrEqual(452);
  });

  test("PDF contains the chart and captions, with enough room on the page", async () => {
    const output = (await tool().execute({ ...input, format: "pdf" }, context)) as RichResult;
    const bytes = bytesOf(output);
    expect(bytes.subarray(0, 5).toString()).toBe("%PDF-");
    expect(bytes.toString("latin1")).toContain("/Subtype /Image");
    expect(output.structured.pages).toBe(1);
    await Bun.write("/tmp/eneo-report-with-chart.pdf", bytes);
  });

  test("templates and revisions keep embedded media with collision-free relationships", async () => {
    const first = bytesOf((await tool().execute(input, context)) as RichResult);
    const download = (async (source: string) => ({
      bytes: source.endsWith("template") ? first : png,
      contentType: source.endsWith("template")
        ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        : "image/png",
      name: source.endsWith("template") ? "report.docx" : "chart.png",
    })) as unknown as typeof downloadFile;
    const templateUrl = url.replace("token=current", "token=template");
    for (const mode of ["template", "revises"]) {
      const output = (await tool(png, download).execute(
        { ...input, [mode]: { url: templateUrl, filename: "report.docx" } },
        context,
      )) as RichResult;
      const zip = await JSZip.loadAsync(bytesOf(output));
      const xml = await zip.file("word/document.xml")!.async("string");
      const rels = await zip.file("word/_rels/document.xml.rels")!.async("string");
      const id = /r:embed="([^"]+)"/.exec(xml)![1]!;
      const relationship = [...rels.matchAll(/<Relationship\b[^>]*\/>/g)].find((r) =>
        r[0].includes(`Id="${id}"`),
      )![0];
      const target = /Target="([^"]+)"/.exec(relationship)![1]!;
      expect(await zip.file(`word/${target}`)!.async("nodebuffer")).toEqual(png);
      const ids = [...rels.matchAll(/\bId="([^"]+)"/g)].map((m) => m[1]);
      expect(new Set(ids).size).toBe(ids.length);
    }
    const size = await pageContentSize(first);
    expect(size.width).toBeGreaterThan(400);
    expect(size.height).toBeGreaterThan(600);
  });

  test("image references are authorized on every use and foreign origins are rejected", async () => {
    let calls = 0;
    const download = (async () => {
      calls++;
      if (calls > 1) throw new Error("download refused: HTTP 401");
      return { bytes: png, contentType: "image/png", name: "chart.png" };
    }) as unknown as typeof downloadFile;
    const create = tool(png, download);
    await create.execute(input, context);
    await expect(create.execute(input, context)).rejects.toThrow("401");
    await expect(
      create.execute(
        {
          ...input,
          images: [{ ...input.images[0], url: url.replace(origin, "https://foreign.example") }],
        },
        context,
      ),
    ).rejects.toThrow("Only signed Eneo");
    expect(calls).toBe(2);
  });

  test("a Markdown document keeps an image as a line naming the file", async () => {
    const handle = "eneo-file:11111111111141118111111111111111";
    const markdown = bytesOf(
      (await tool().execute({ ...input, format: "md" }, context)) as RichResult,
    ).toString("utf8");
    expect(markdown).toContain(
      `\n![Budget och utfall](${handle} "Figur 1. Budget och utfall i miljoner kronor.")\n`,
    );
    expect(markdown).not.toContain("token=");

    // Revised as Markdown the line stays as it is; as Word it embeds once the file is declared.
    const revised = bytesOf(
      (await tool().execute(
        { title: input.title, format: "md", content: markdown },
        context,
      )) as RichResult,
    ).toString("utf8");
    expect(revised).toBe(markdown);
    const word = (await tool().execute(
      {
        title: input.title,
        format: "docx",
        content: markdown,
        images: [{ url, filename: "generated_image.png" }],
      },
      context,
    )) as RichResult;
    const zip = await JSZip.loadAsync(bytesOf(word));
    expect(Object.keys(zip.files).some((name) => name.startsWith("word/media/"))).toBe(true);
    expect(await zip.file("word/document.xml")!.async("string")).toContain(
      "Figur 1. Budget och utfall i miljoner kronor.",
    );
    await expect(
      tool().execute({ title: input.title, format: "docx", content: markdown }, context),
    ).rejects.toThrow("declared in images");
  });

  test("a Markdown document refuses images it cannot place", async () => {
    const md = { ...input, format: "md" };
    await expect(tool().execute({ ...md, images: [] }, context)).rejects.toThrow("not declared");
    await expect(
      tool().execute(
        { ...md, content: `${md.content}\n\n![Utfall](image:utfall)\n\n![Utfall](image:utfall)` },
        context,
      ),
    ).rejects.toThrow("Image utfall is placed");
    await expect(
      tool().execute(
        { ...md, content: `${md.content}\n\n![Utfall](image:utfall)`, images: [] },
        context,
      ),
    ).rejects.toThrow("Images budget, utfall are placed");
    await expect(
      tool().execute({ ...md, content: "Se ![diagram](image:budget) här." }, context),
    ).rejects.toThrow("line of its own");
    await expect(tool().execute({ ...md, content: "Ingen bild." }, context)).rejects.toThrow(
      "not placed",
    );
    await expect(tool(Buffer.from("<svg/>")).execute(md, context)).rejects.toThrow(
      "valid PNG or JPEG",
    );
  });

  test("rejects undeclared images, oversized rasters and duplicate IDs", async () => {
    await expect(tool().execute({ ...input, images: [] }, context)).rejects.toThrow(
      "declared in images",
    );
    await expect(
      tool().execute({ ...input, images: [input.images[0], input.images[0]] }, context),
    ).rejects.toThrow("unique");
    await expect(tool(Buffer.from("<svg/>")).execute(input, context)).rejects.toThrow(
      "valid PNG or JPEG",
    );
    const enormous = Buffer.from(png);
    enormous.writeUInt32BE(100000, 16);
    expect(() => imageDimensions(enormous)).toThrow("16 megapixels");
    await expect(
      tool().execute(
        { ...input, images: [{ ...input.images[0], filename: "chart.svg" }] },
        context,
      ),
    ).rejects.toThrow();
  });

  test("declared images render inside confinement", async () => {
    const create = documentTools(
      documentConfigSchema.parse({}),
      fileRenderer(async (job) => {
        return (await runIsolated({ job }, 30000)) as { bytes: number; pages?: number };
      }),
      {
        allowedFileOrigins: [],
        maxBytes: 20e6,
        timeoutMs: 1000,
        download: (async () => ({
          bytes: png,
          contentType: "image/png",
          name: "chart.png",
        })) as unknown as typeof downloadFile,
      },
    )[0]!;
    const output = (await create.execute(input, context)) as RichResult;
    expect(output.files[0]!.mimeType).toContain("wordprocessingml");
  });
});
