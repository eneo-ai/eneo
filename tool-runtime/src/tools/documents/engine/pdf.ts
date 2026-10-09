// Runs inside sandbox children only. A PDF is the document laid out by WeasyPrint from HTML
// and CSS, tagged for accessibility (PDF/UA structure), in the organisation's profile: the
// document is first rendered into its Word template, and the page, fonts, colours, header,
// footer and logo are read from that file (pdf-profile.ts). WeasyPrint runs as a Python
// sidecar the runtime image installs; the child spawns it inside its own confinement with
// the render directory as the only place it may read or write.
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseMarkdown } from "../markdown/parse";
import type { DocumentSpec } from "../ports";
import { renderHtml, type HtmlImage } from "./html";
import { fitImage, type DocumentImages } from "./images";
import { pdfProfile, profileCss } from "./pdf-profile";
import { RenderError, type Rendered } from "./render";
import { renderIntoTemplate } from "./word/apply";
import { LANGUAGE_TAGS } from "./word/builtin";

/** The Python with WeasyPrint; the image installs it here, a developer may point elsewhere. */
export const PDF_PYTHON = process.env.PDF_PYTHON ?? "/opt/pdf/bin/python3";
const SCRIPT = fileURLToPath(new URL("../../../../scripts/render_pdf.py", import.meta.url));
const SIDE_CAR_TIMEOUT_MS = 20_000;
const MAX_STDERR = 2_000;

/** Whether the sidecar is installed; tests skip PDF cases without it. */
export async function pdfAvailable(): Promise<boolean> {
  return (await Bun.file(PDF_PYTHON).exists()) && (await Bun.file(SCRIPT).exists());
}

export async function renderPdf(
  document: Extract<DocumentSpec, { kind: "markdown" }>,
  options: { template: Buffer; images: DocumentImages; organisationName?: string },
): Promise<Rendered> {
  if (!(await pdfAvailable()))
    throw new RenderError("PDF rendering is not installed on this runtime (WeasyPrint sidecar).");
  // The Word rendering carries the template's filled header, footer and styles.
  const docx = await renderIntoTemplate(options.template, document, {
    images: options.images,
    organisationName: options.organisationName,
  });
  const directory = await mkdtemp(join(process.env.TMPDIR ?? tmpdir(), "eneo-pdf-"));
  await mkdir(join(directory, "cache"), { recursive: true, mode: 0o700 });
  const profile = await pdfProfile(docx, directory);
  // Figures are sized as in the Word file: to the page's content area, with room for a caption.
  const toPt = 72 / 25.4;
  const { page } = profile;
  const content = {
    width: (page.widthMm - page.marginMm.left - page.marginMm.right) * toPt,
    height: (page.heightMm - page.marginMm.top - page.marginMm.bottom) * toPt,
  };
  const images = new Map<string, HtmlImage>();
  let index = 0;
  for (const [id, image] of options.images) {
    const file = `img-${index++}.${image.type}`;
    await writeFile(join(directory, file), image.bytes, { mode: 0o600 });
    const size = fitImage(image, content.width, content.height - 120);
    images.set(id, {
      file,
      ...(image.caption ? { caption: image.caption } : {}),
      widthPt: size.width,
      heightPt: size.height,
    });
  }
  const blocks = parseMarkdown(document.content);
  const lead = !(blocks[0]?.type === "heading" && blocks[0].level === 1);
  const language = LANGUAGE_TAGS[document.language] ?? document.language;
  const html = renderHtml(blocks, {
    title: document.title,
    language,
    author: options.organisationName,
    lead,
    images,
    header: profile.header,
    footer: profile.footer,
  });
  await writeFile(join(directory, "document.html"), html, { mode: 0o600 });
  await writeFile(join(directory, "document.css"), profileCss(profile), { mode: 0o600 });
  const job = {
    base_dir: directory,
    html_path: join(directory, "document.html"),
    css_path: join(directory, "document.css"),
    output_path: join(directory, "output.pdf"),
    pdf_variant: "pdf/ua-1",
  };
  await writeFile(join(directory, "job.json"), JSON.stringify(job), { mode: 0o600 });
  const pages = await runSidecar(directory);
  const buffer = await readFile(job.output_path);
  if (buffer.subarray(0, 5).toString() !== "%PDF-")
    throw new RenderError("The PDF renderer produced no document.");
  return { buffer, pages };
}

async function runSidecar(directory: string): Promise<number> {
  const child = Bun.spawn([PDF_PYTHON, "-I", "-B", SCRIPT, join(directory, "job.json")], {
    cwd: directory,
    env: {
      HOME: directory,
      TMPDIR: directory,
      XDG_CACHE_HOME: join(directory, "cache"),
      LANG: "C.UTF-8",
      LC_ALL: "C.UTF-8",
    },
    stdin: "ignore",
    stdout: "pipe",
    stderr: "pipe",
  });
  const timer = setTimeout(() => child.kill("SIGKILL"), SIDE_CAR_TIMEOUT_MS);
  try {
    const [stdout, stderr, code] = await Promise.all([
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
      child.exited,
    ]);
    if (code !== 0) {
      const detail = stderr.trim().split("\n").filter(Boolean).at(-1)?.slice(0, MAX_STDERR);
      throw new RenderError(
        `The PDF renderer failed${detail ? `: ${detail}` : ""}. Simplify the document and retry.`,
      );
    }
    const pages = Number((JSON.parse(stdout) as { pages?: unknown }).pages);
    return Number.isInteger(pages) && pages > 0 ? pages : 1;
  } finally {
    clearTimeout(timer);
  }
}
