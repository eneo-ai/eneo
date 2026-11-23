import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import { fetchReference, pictureSourceReference, type ReferenceAccess } from "../files/reference";
import { RichResult, type ToolDefinition } from "../types";
import {
  OUTPUT_DIRECTORY,
  SOURCE_FILE,
  type ExtractImagesJob,
  type ExtractImagesResult,
  type PictureFileKind,
} from "./ports";

/** Runs an extraction job in a sandbox child (see sandbox.ts); injected so tests can run in-process. */
export type PictureExtractor = (job: ExtractImagesJob) => Promise<ExtractImagesResult>;

/** Pictures per call: what Eneo admits from one tool result. */
export const PICTURES_PER_CALL = 4;
/** PDF pages searched for pictures. */
const MAX_PDF_PAGES = 200;

export function pictureTools(extract: PictureExtractor, access: ReferenceAccess): ToolDefinition[] {
  const input = z.object({
    file: pictureSourceReference.describe(
      "The attached file to take pictures out of: its signed url and filename, exactly as given in the attachment reference.",
    ),
    page: z
      .number()
      .int()
      .min(1)
      .max(100_000)
      .optional()
      .describe("PDF only: return only the pictures on this page (1 is the first page)."),
    offset: z
      .number()
      .int()
      .min(0)
      .max(100_000)
      .default(0)
      .describe(
        "The number of pictures to skip. Pass the next_offset of the previous call to get the pictures after it.",
      ),
  });
  return [
    {
      name: "extract_images",
      title: "Extract images from file",
      description: `Take the pictures out of an attached PDF, Word (.docx) or PowerPoint (.pptx) file as images of their own. Use it when a document's pictures are needed outside it, for example to carry its figures over into a new document. Each picture is saved as an image file of the conversation and shown to the user, and comes back with a file reference that a document tool's images input accepts; write alt text there that describes what the picture shows. A call returns up to ${PICTURES_PER_CALL} pictures in document order and says how many the file has; pass next_offset as offset to get the next ones. Only pictures stored as images can be extracted: a chart or diagram drawn as vector graphics is not one, and neither is the text of a page. A picture the file repeats, such as a logo on every page, is returned once. When total is 0, tell the user the file has no extractable pictures; never describe a picture as extracted when none came back. This tool does not read a file's text.`,
      inputSchema: input.shape,
      readOnly: true,
      async execute(raw, ctx) {
        const args = input.parse(raw);
        const fileKind = args.file.filename.split(".").pop()!.toLowerCase() as PictureFileKind;
        const source = await fetchReference(args.file, ctx, access);
        const directory = await mkdtemp(join(tmpdir(), "eneo-tool-runtime-pictures-"));
        try {
          await writeFile(join(directory, SOURCE_FILE), source.bytes, {
            mode: 0o600,
          });
          await mkdir(join(directory, OUTPUT_DIRECTORY), { mode: 0o700 });
          const page = fileKind === "pdf" ? args.page : undefined;
          const { total, pictures } = await extract({
            kind: "extract_images",
            directory,
            fileKind,
            offset: args.offset,
            limit: PICTURES_PER_CALL,
            maxPages: MAX_PDF_PAGES,
            ...(page !== undefined ? { page } : {}),
          });
          const scope = {
            file: args.file.filename,
            ...(page !== undefined ? { page } : {}),
          };
          if (!total)
            return {
              ...scope,
              total: 0,
              note:
                fileKind === "pdf"
                  ? "No pictures are stored as images here. Charts and diagrams drawn as vector graphics cannot be extracted."
                  : "No raster pictures are embedded in this file. Vector drawings and charts built in the document cannot be extracted.",
            };
          if (!pictures.length)
            return {
              ...scope,
              total,
              note: `Offset ${args.offset} is past the last picture.`,
            };
          const images = [];
          for (const picture of pictures)
            images.push({
              data: (await readFile(join(directory, OUTPUT_DIRECTORY, picture.file))).toString(
                "base64",
              ),
              mimeType: picture.mimeType,
            });
          const end = args.offset + pictures.length;
          return new RichResult(
            {
              ...scope,
              total,
              // Numbered as the image placeholders of this result are: Image 1, Image 2, ...
              images: pictures.map((picture, index) => ({
                image: index + 1,
                number_in_file: args.offset + index + 1,
                ...(picture.page !== undefined ? { page: picture.page } : {}),
                width: picture.width,
                height: picture.height,
              })),
              ...(end < total ? { next_offset: end } : {}),
              delivered:
                "Each image is saved as a file of this conversation and shown to the user. To place one in a document, pass its file reference to the document tool's images input with alt text describing what it shows.",
            },
            [],
            images,
          );
        } finally {
          await rm(directory, { recursive: true, force: true });
        }
      },
    },
  ];
}
